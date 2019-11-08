#
# Copyright (c) 2018 ISP RAS (http://www.ispras.ru)
# Ivannikov Institute for System Programming of the Russian Academy of Sciences
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

from core.vtg.emg.common.c.types import import_declaration, Declaration


class Variable:
    """The class represents a C variable."""

    name_re = re.compile(r'\(?\*?%s\)?')

    def __init__(self, name, declaration):
        self._name = name
        self._declaration = None

        self.use = 0
        self.value = None
        self.declaration_files = set()
        self.initialization_file = None

        if not declaration:
            declaration = 'void f(void)'
        if isinstance(declaration, str):
            self._declaration = import_declaration(declaration)
        elif issubclass(type(declaration), Declaration):
            self._declaration = declaration
        else:
            raise ValueError("Attempt to add variable {!r} without signature".format(name))

    @property
    def name(self):
        return self._name

    @property
    def declaration(self):
        return self._declaration

    def declare_with_init(self, scope=None):
        """
        Return a string with the variable initialization.

        :return: String.
        """
        # Get declaration
        declaration = self.declare(extern=False, scope=scope)

        # Add memory allocation
        if self.value:
            declaration += " = {}".format(self.value)

        return declaration

    def declare(self, extern=False, scope=None):
        """
        Returns a string with the variable declaration.

        :param extern: Add an 'extern' prefix if True.
        :return: Declartion string.
        """

        # Generate declaration
        expr = self._declaration.to_string(self._name, typedef='complex_and_params', scope=scope)

        # Add extern prefix
        if extern:
            expr = "extern " + expr

        return expr


class Function:
    """The class represents a C function."""

    def __init__(self, name, declaration=None):
        self._name = name
        self._declaration = None
        self.body = []
        self.calls = dict()
        self.called_at = dict()
        self.declaration_files = set()
        self.definition_file = None
        self.header_files = list()

        if not declaration:
            declaration = 'void f(void)'
        if isinstance(declaration, str):
            self._declaration = import_declaration(declaration)
        elif issubclass(declaration, Declaration):
            self._declaration = declaration
        else:
            raise ValueError("Attempt to add function {!r} without signature".format(name))

    @property
    def name(self):
        return self._name

    @property
    def declaration(self):
        return self._declaration

    @property
    def files_called_at(self):
        """
        Provide a list of file names where the function has been called.

        :return: A list with file names.
        """
        return self.called_at.keys()

    def call_in_function(self, func_obj, parameters=None):
        """
        Save information that the function calls in her body an another provided function with given arguments.

        :param func_obj: Object of the called function.
        :param parameters: List of parameters. Currently all non-function pointers are None and for function pointers
                           the value is a explicit function name.
        :return: None
        """
        if func_obj.name not in self.calls:
            self.calls[func_obj.name] = []
        if parameters is not None:
            p = dict(parameters)
            self.calls[func_obj.name].append([p.get(str(i), 0)
                                              for i in range(1, len(func_obj.declaration.parameters) + 1)])

    def add_call(self, func, path):
        """
        Add information that the function is called in the function privided as a parameter.

        :param func: Function that calls this one.
        :param path: File where it is happened.
        :return: None.
        """
        if path not in self.called_at:
            self.called_at[path] = {func}
        else:
            self.called_at[path].add(func)

    def declare(self, extern=False, scope=None):
        """
        Provide a string with the declaration of this function.

        :param extern: Add the 'extern' prefix.
        :return: Declaration string.
        """
        declaration = self._declaration.to_string(self._name, typedef='complex_and_params', scope=scope)
        declaration += ';'

        if extern:
            declaration = "extern " + declaration
        return [declaration + "\n"]

    def define(self, scope=None):
        """
        Provide a list of strings with the definition of the function.

        :return: List of strings.
        """
        declaration = self._declaration.define_with_args(self._name, typedef='complex_and_params', scope=scope)
        lines = ['/* AUX_FUNC {} */\n'.format(self._name)]
        lines.append(declaration + " {\n")
        lines.extend(['\t{}\n'.format(stm) for stm in self.body])
        lines.append("}\n")
        return lines


class Macro:
    """The class represents a macro."""

    def __init__(self, name):
        self.name = name
        self.parameters = dict()

    def add_parameters(self, path, parameters):
        """
        Add informtion that this macro was used with the given parameters in the given file.

        :param path: File where the macro was used.
        :param parameters: List of parameter strings.
        :return: None.
        """
        if path not in parameters:
            self.parameters[path] = [parameters]
        else:
            self.parameters[path].append(parameters)
