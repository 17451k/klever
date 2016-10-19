#
# Copyright (c) 2014-2016 ISPRAS (http://www.ispras.ru)
# Institute for System Programming of the Russian Academy of Sciences
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import re
import os
from core.avtg.emg.common.signature import Declaration, Pointer, Function, Primitive, import_declaration
from core.avtg.emg.common import get_conf_property


class CModel:

    mem_function_map = {
        "ALLOC": "ldv_xmalloc",
        "UALLOC": "ldv_xmalloc_unknown_size",
        "ZALLOC": "ldv_zalloc"
    }
    free_function_map = {
        "FREE": "ldv_free"
    }
    irq_function_map = {
        "IN_INTERRUPT_CONTEXT": 'ldv_in_interrupt_context',
        "SWITCH_TO_IRQ_CONTEXT": 'ldv_switch_to_interrupt_context',
        "SWITCH_TO_PROCESS_CONTEXT": 'ldv_switch_to_process_context'
    }

    def __init__(self, logger, conf, workdir, files, entry_point_name, entry_file):
        self.entry_file = entry_file
        self.entry_name = entry_point_name
        self.files = files
        self.types = list()
        self._logger = logger
        self._conf = conf
        self._workdir = workdir
        self._variables_declarations = dict()
        self._variables_initializations = dict()
        self._function_definitions = dict()
        self._function_declarations = dict()
        self._before_aspects = dict()
        self._common_aspects = list()
        self.__external_allocated = dict()

    def add_before_aspect(self, code, file=None):
        # Prepare code
        body = ['before: file ("$this") \n', '{\n']
        body.extend(code)
        body.append('\n}\n')

        if file:
            files = [file]
        else:
            files = self.files

        # Add code
        for file in files:
            if file not in self._before_aspects:
                self._before_aspects[file] = list()
            self._before_aspects[file].append(body)

        return

    def propogate_aux_function(self, analysis, automaton, function):
        # Determine files to export
        files = set()
        if automaton.process.category == "kernel models":
            # Calls
            function_obj = analysis.get_kernel_function(automaton.process.name)
            files.update(set(function_obj.files_called_at))
            for caller in (c for c in function_obj.functions_called_at):
                # Caller definitions
                files.update(set(analysis.get_modules_function_files(caller)))

        # Export
        for file in files:
            self.add_function_declaration(file, function, extern=True)

    def add_function_definition(self, file, function):
        if not file:
            raise RuntimeError('Always expect file to place function definition')
        if file not in self._function_definitions:
            self._function_definitions[file] = dict()
        if self.entry_file not in self._function_definitions:
            self._function_definitions[self.entry_file] = dict()

        self._function_definitions[file][function.name] = ['/* AUX_FUNC */\n'] + list(function.get_definition())
        self.add_function_declaration(file, function, extern=False)

    def add_function_declaration(self, file, function, extern=False):
        if file not in self._function_declarations:
            self._function_declarations[file] = dict()

        if extern and function.name in self._function_declarations[file]:
            return
        self._function_declarations[file][function.name] = function.get_declaration(extern=extern)

    def add_global_variable(self, variable, file, extern=False):
        if not file and variable.file:
            file = variable.file
        elif not file:
            file = self.entry_file

        if file not in self._variables_declarations:
            self._variables_declarations[file] = dict()
        if file not in self._variables_initializations:
            self._variables_initializations[file] = dict()

        if extern and variable.name not in self._variables_declarations[file]:
            self._variables_declarations[file][variable.name] = variable.declare(extern=extern) + ";\n"
        elif not extern:
            self._variables_declarations[file][variable.name] = variable.declare(extern=extern) + ";\n"
            if variable.value and variable.file and \
                    ((type(variable.declaration) is Pointer and type(variable.declaration.points) is Function) or
                     type(variable.declaration) is Primitive):
                self._variables_initializations[file][variable.name] = variable.declare_with_init() + ";\n"
            elif not variable.value and type(variable.declaration) is Pointer:
                if file not in self.__external_allocated:
                    self.__external_allocated[file] = []
                self.__external_allocated[file].append(variable)

    def text_processor(self, automaton, statement):
        models = FunctionModels(self._conf, self.mem_function_map, self.free_function_map, self.irq_function_map)
        return models.text_processor(automaton, statement)

    def add_function_model(self, function, body):
        new_aspect = Aspect(function.identifier, function)
        new_aspect.body = body
        self._common_aspects.append(new_aspect)

    def print_source_code(self, additional_lines):
        aspect_dir = "aspects"
        self._logger.info("Create directory for aspect files {}".format("aspects"))
        os.makedirs(aspect_dir.encode('utf8'), exist_ok=True)

        addictions = dict()
        for file in self.files:
            # Generate function declarations
            self._logger.info('Add aspects to a file {!r}'.format(file))
            # Aspect text
            lines = list()

            if len(additional_lines) > 0:
                    lines.append("\n")
                    lines.append("/* EMG additional aspects */\n")
                    lines.extend(additional_lines)
                    lines.append("\n")

            if len(self._before_aspects[file]) > 0:
                for aspect in self._before_aspects[file]:
                    lines.append("\n")
                    lines.append("/* EMG aspect */\n")
                    lines.extend(aspect)
                    lines.append("\n")

            # Add model itself
            lines.append('after: file ("$this")\n')
            lines.append('{\n')

            for tp in self.types:
                lines.append(tp.to_string('') + " {\n")
                for field in sorted(list(tp.fields.keys())):
                    lines.append("\t{};\n".format(tp.fields[field].to_string(field)))
                lines.append("};\n")
                lines.append("\n")

            lines.append("/* EMG Function declarations */\n")
            if file in self._function_declarations:
                for function in sorted(self._function_declarations[file].keys()):
                    lines.extend(self._function_declarations[file][function])

            lines.append("\n")
            lines.append("/* EMG variable declarations */\n")
            if file in self._variables_declarations:
                for variable in sorted(self._variables_declarations[file].keys()):
                    lines.extend(self._variables_declarations[file][variable])

            lines.append("\n")
            lines.append("/* EMG variable initialization */\n")
            if file in self._variables_initializations:
                for variable in sorted(self._variables_initializations[file].keys()):
                    lines.extend(self._variables_initializations[file][variable])

            lines.append("\n")
            lines.append("/* EMG function definitions */\n")
            if file in self._function_definitions:
                for function in sorted(self._function_definitions[file].keys()):
                    lines.extend(self._function_definitions[file][function])
                    lines.append("\n")

            lines.append("}\n")
            lines.append("/* EMG kernel function models */\n")
            for aspect in self._common_aspects:
                lines.extend(aspect.get_aspect())
                lines.append("\n")

            name = "aspects/ldv_{}.aspect".format(os.path.splitext(os.path.basename(file))[0])
            with open(name, "w", encoding="utf8") as fh:
                fh.writelines(lines)

            path = os.path.relpath(name, self._workdir)
            self._logger.info("Add aspect file {!r}".format(path))
            addictions[file] = path

        return addictions

    def compose_entry_point(self, given_body):
        ep = FunctionDefinition(
            self.entry_name,
            self.entry_file,
            "void {}(void)".format(self.entry_name),
            False
        )
        body = []

        # Init external allocated pointers
        cnt = 0
        functions = []
        if len(self.__external_allocated.keys()) > 0:
            for file in sorted([f for f in self.__external_allocated.keys() if len(self.__external_allocated[f]) > 0]):
                func = FunctionDefinition('ldv_allocate_external_{}'.format(cnt),
                                          file,
                                          "void ldv_allocate_external_{}(void)".format(cnt),
                                          True)

                init = ["{} = {}();".format(var.name, 'external_allocated_data') for
                        var in self.__external_allocated[file]]
                func.body = init

                self.add_function_definition(file, func)
                self.add_function_declaration(self.entry_file, func, extern=True)
                functions.append(func)
                cnt += 1

            gl_init = FunctionDefinition('ldv_initialize_external_data',
                                         self.entry_file,
                                         'void ldv_initialize_external_data(void)')
            init_body = ['{}();'.format(func.name) for func in functions]
            gl_init.body = init_body
            self.add_function_definition(self.entry_file, gl_init)
            body.extend([
                '/* Initialize external data */',
                'ldv_initialize_external_data();'
            ])

        body = [
            "ldv_initialize();",
        ] + body + given_body

        ep.body = body
        self.add_function_definition(self.entry_file, ep)
        return body


class Variable:
    name_re = re.compile("\(?\*?%s\)?")

    def __init__(self, name, file, signature, export=False):
        self.name = name
        self.file = file
        self.export = export
        self.value = None
        self.use = 0

        if type(signature) is str:
            self.declaration = import_declaration(signature)
        elif issubclass(type(signature), Declaration):
            self.declaration = signature
        else:
            raise ValueError("Attempt to create variable {} without signature".format(name))

    def declare_with_init(self):
        # Ger declaration
        declaration = self.declare(extern=False)

        # Add memory allocation
        if self.value:
            declaration += " = {}".format(self.value)

        return declaration

    def declare(self, extern=False):
        # Generate declaration
        expr = self.declaration.to_string(self.name)

        # Add extern prefix
        if extern:
            expr = "extern " + expr

        return expr


class FunctionDefinition:

    def __init__(self, name, file, signature=None, export=False):
        self.name = name
        self.file = file
        self.export = export
        self.body = []

        if not signature:
            signature = 'void f(void)'
        self.declaration = import_declaration(signature)

    def get_declaration(self, extern=False):
        declaration = self.declaration.to_string(self.name)
        declaration += ';'

        if extern:
            declaration = "extern " + declaration
        return [declaration + "\n"]

    def get_definition(self):
        declaration = '{} {}({})'.format(self.declaration.return_value.to_string(), self.name,
                                         ', '.join([self.declaration.parameters[index].to_string('arg{}'.format(index))
                                                    for index in range(len(self.declaration.parameters))]))

        lines = list()
        lines.append(declaration + " {\n")
        lines.extend(['\t{}\n'.format(stm) for stm in self.body])
        lines.append("}\n")
        return lines


class Aspect(FunctionDefinition):

    def __init__(self, name, declaration, aspect_type="after"):
        self.name = name
        self.declaration = declaration
        self.aspect_type = aspect_type
        self.body = []

    def get_aspect(self):
        lines = list()
        lines.append("after: call({}) ".format("$ {}(..)".format(self.name)) +
                     " {\n")
        lines.extend(['\t{}\n'.format(stm) for stm in self.body])
        lines.append("}\n")
        return lines


class FunctionModels:

    mem_function_template = "\$({})\(%({})%(?:,\s?(\w+))?\)"
    simple_function_template = "\$({})\("
    access_template = '\w+(?:(?:[.]|->)\w+)*'
    mem_function_re = re.compile(mem_function_template.format('\w+', access_template))
    simple_function_re = re.compile(simple_function_template.format('\w+'))
    access_re = re.compile('(%{}%)'.format(access_template))
    arg_re = re.compile('(\$ARG\d)')

    def __init__(self, conf, mem_function_map, free_function_map, irq_function_map):
        self._conf = conf
        self.mem_function_map = mem_function_map
        self.free_function_map = free_function_map
        self.irq_function_map = irq_function_map

    def init_pointer(self, signature):
        if get_conf_property(self._conf, 'allocate with sizeof'):
            return "{}(sizeof({}))".format(self.mem_function_map["ALLOC"], signature.points.to_string(''))
        else:
            return "{}(sizeof({}))".format(self.mem_function_map["ALLOC"], '0')

    def text_processor(self, automaton, statement):
        # Replace function names
        stms = []
        matched = False

        # First replace simple replacements
        statement = statement.replace('$res', 'arg0')
        for pattern in self.arg_re.findall(statement):
            replacement = pattern.replace('$ARG', 'arg')
            statement = statement.replace(pattern, replacement)

        # Replace function calls
        for fn in self.simple_function_re.findall(statement):
            matched = True

            # Bracket is required to ignore CIF expressions like $res or $arg1
            if fn in self.mem_function_map or fn in self.free_function_map:
                access = self.mem_function_re.search(statement).group(2)
                if fn in self.mem_function_map:
                    replacement = self._replace_mem_call
                else:
                    replacement = self._replace_free_call

                accesses = automaton.process.resolve_access('%{}%'.format(access))
                for access in accesses:
                    ualloc_flag = True
                    if access.interface:
                        if access.interface.manually_specified:
                            ualloc_flag = False
                        signature = access.label.get_declaration(access.interface.identifier)
                    else:
                        signature = access.label.prior_signature

                    if signature:
                        if access.interface:
                            var = automaton.determine_variable(access.label, access.list_interface[0].identifier)
                        else:
                            var = automaton.determine_variable(access.label)

                        if type(var.declaration) is Pointer:
                            self.signature = var.declaration
                            self.ualloc_flag = ualloc_flag
                            new = self.mem_function_re.sub(replacement, statement)
                            new = access.replace_with_variable(new, var)
                            stms.append(new)
            elif fn in self.irq_function_map:
                statement = self.simple_function_re.sub(self.irq_function_map[fn] + '(', statement)
                stms.append(statement)
            else:
                raise NotImplementedError("Model function '${}' is not supported".format(fn))

        if not matched:
            stms = [statement]

        # Replace rest accesses
        final = []
        for original_stm in stms:
            # Collect dublicates
            stm_set = {original_stm}

            while len(stm_set) > 0:
                stm = stm_set.pop()

                if self.access_re.search(stm):
                    expression = self.access_re.search(stm).group(1)
                    accesses = automaton.process.resolve_access(expression)
                    for access in accesses:
                        if access.interface:
                            var = automaton.determine_variable(access.label, access.list_interface[0].identifier)
                        else:
                            var = automaton.determine_variable(access.label)

                        stm = access.replace_with_variable(stm, var)
                        stm_set.add(stm)
                else:
                    final.append(stm)

        return final

    def _replace_mem_call(self, match):
        function, label_name, flag = match.groups()
        size = '0'

        if function not in self.mem_function_map:
            raise NotImplementedError("Model of {} is not supported".format(function))
        elif not self.mem_function_map[function]:
            raise NotImplementedError("Set implementation for the function {}".format(function))

        if type(self.signature) is Pointer:
            if function == 'ALLOC' and self.ualloc_flag:
                # Do not alloc memory anyway for unknown resources anyway to avoid incomplete type errors
                function = 'UALLOC'
            if get_conf_property(self._conf, 'disable ualloc') and function == 'UALLOC':
                function = 'ALLOC'
            if function != 'UALLOC' and get_conf_property(self._conf, 'allocate with sizeof'):
                size = 'sizeof({})'.format(self.signature.points.to_string(''))

            return "{}({})".format(self.mem_function_map[function], size)
        else:
            raise ValueError('This is not a pointer')

    def _replace_free_call(self, match):
        function, label_name, flag = match.groups()
        if function not in self.free_function_map:
            raise NotImplementedError("Model of {} is not supported".format(function))
        elif not self.free_function_map[function]:
            raise NotImplementedError("Set implementation for the function {}".format(function))

        # Create function call
        if type(self.signature) is Pointer:
            return "{}(%{}%)".format(self.free_function_map[function], label_name)
        else:
            raise ValueError('This is not a pointer')

__author__ = 'Ilja Zakharov <ilja.zakharov@ispras.ru>'
