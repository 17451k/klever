#
# Copyright (c) 2014-2015 ISPRAS (http://www.ispras.ru)
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

import copy
import re

from core.avtg.emg.grammars.signature import setup_parser, parse_signature


__type_collection = {}

__typedefs = {}

__noname_identifier = 0


def setup_collection(collection, typedefs):
    global __type_collection
    global __typedefs

    __type_collection = collection
    __typedefs = typedefs


def new_identifier():
    global __noname_identifier

    __noname_identifier += 1
    return __noname_identifier


def check_null(declaration, value):
    check = re.compile('[\s]*[(]?[\s]*0[\s]*[)]?[\s]*')
    if (type(declaration) is Function or (type(declaration) is Pointer and type(declaration.points) is Function)) and \
            check.fullmatch(value):
        return False
    else:
        return True


def extract_name(signature):
    try:
        ast = parse_signature(signature)
    except:
        raise ValueError("Cannot parse signature: {}".format(signature))

    if 'declarator' in ast and len(ast['declarator']) > 0 and 'identifier' in ast['declarator'][-1] and \
            ast['declarator'][-1]['identifier']:
        return ast['declarator'][-1]['identifier']
    else:
        return None


def import_typedefs(tds):
    global __typedefs

    for td in sorted(tds):
        ast = parse_signature(td)
        name = ast['declarator'][-1]['identifier']
        __typedefs[name] = ast


def import_declaration(signature, ast=None, track_typedef=False):
    global __type_collection
    global __typedefs
    typedef = None

    if not ast:
        try:
            ast = parse_signature(signature)
        except:
            raise ValueError("Cannot parse signature: {}".format(signature))

    if 'declarator' not in ast or ('declarator' in ast and len(ast['declarator']) == 0):
        if 'specifiers' in ast and 'category' in ast['specifiers'] and 'identifier' in ast['specifiers']:
            ret = InterfaceReference(ast)
        elif 'specifiers' in ast and ast['specifiers'] == '$':
            ret = UndefinedReference(ast)
        elif 'specifiers' in ast and 'type specifier' in ast['specifiers'] and \
                ast['specifiers']['type specifier']['class'] == 'typedef' and \
                ast['specifiers']['type specifier']['name'] in __typedefs:
            ret = import_declaration(None, copy.deepcopy(__typedefs[ast['specifiers']['type specifier']['name']]))
            ret.typedef = ast['specifiers']['type specifier']['name']
            typedef = ret.typedef
        elif 'specifiers' in ast and 'type specifier' in ast['specifiers'] and \
                ast['specifiers']['type specifier']['class'] == 'structure':
            ret = Structure(ast)
        elif 'specifiers' in ast and 'type specifier' in ast['specifiers'] and \
                ast['specifiers']['type specifier']['class'] == 'enum':
            ret = Enum(ast)
        elif 'specifiers' in ast and 'type specifier' in ast['specifiers'] and \
                ast['specifiers']['type specifier']['class'] == 'union':
            ret = Union(ast)
        else:
            ret = Primitive(ast)
    else:
        if len(ast['declarator']) == 1 and \
                ('pointer' not in ast['declarator'][-1] or ast['declarator'][-1]['pointer'] == 0) and \
                ('arrays' not in ast['declarator'][-1] or len(ast['declarator'][-1]['arrays']) == 0):
            if 'specifiers' not in ast:
                ret = Function(ast)
            else:
                if ast['specifiers']['type specifier']['class'] == 'structure':
                    ret = Structure(ast)
                elif ast['specifiers']['type specifier']['class'] == 'enum':
                    ret = Enum(ast)
                elif ast['specifiers']['type specifier']['class'] == 'union':
                    ret = Union(ast)
                elif ast['specifiers']['type specifier']['class'] == 'typedef' and \
                        ast['specifiers']['type specifier']['name'] in __typedefs:
                    ret = import_declaration(None,
                                             copy.deepcopy(__typedefs[ast['specifiers']['type specifier']['name']]))
                    ret.typedef = ast['specifiers']['type specifier']['name']
                    typedef = ret.typedef
                else:
                    ret = Primitive(ast)
        elif 'arrays' in ast['declarator'][-1] and len(ast['declarator'][-1]['arrays']) > 0:
            ret = Array(ast)
            if track_typedef and ret.element.typedef:
                typedef = ret.element.typedef
        elif 'pointer' not in ast['declarator'][-1] or ast['declarator'][-1]['pointer'] > 0:
            ret = Pointer(ast)
            if track_typedef and ret.points.typedef:
                typedef = ret.points.typedef
        else:
            raise NotImplementedError

    if ret.identifier not in __type_collection:
        __type_collection[ret.identifier] = ret
    else:
        if ret.typedef:
            __type_collection[ret.identifier].typedef = ret.typedef
        if isinstance(ret, Function):
            if ret.ret_typedef and not __type_collection[ret.identifier].ret_typedef:
                __type_collection[ret.identifier].ret_typedef = ret.ret_typedef
            for index, pt in enumerate(__type_collection[ret.identifier].params_typedef):
                if not pt and ret.params_typedef[index]:
                    __type_collection[ret.identifier].params_typedef[index] = ret.params_typedef[index]
        ret = __type_collection[ret.identifier]

    if not track_typedef:
        return ret
    else:
        return ret, typedef


def refine_declaration(interfaces, declaration):
    global __type_collection

    if declaration.clean_declaration:
        raise ValueError('Cannot clean already cleaned declaration')

    if type(declaration) is UndefinedReference:
        return None
    elif type(declaration) is InterfaceReference:
        if declaration.interface in interfaces and \
                interfaces[declaration.interface].declaration.clean_declaration:
            if declaration.pointer:
                return interfaces[declaration.interface].declaration.take_pointer
            else:
                return interfaces[declaration.interface].declaration
        else:
            return None
    elif type(declaration) is Function:
        refinement = False
        new = copy.deepcopy(declaration)

        # Refine the same object
        if new.return_value and not new.return_value.clean_declaration:
            rv = refine_declaration(interfaces, new.return_value)
            if rv:
                new.return_value = rv
                refinement = True

        for index in range(len(new.parameters)):
            if type(new.parameters[index]) is not str and \
                    not new.parameters[index].clean_declaration:
                pr = refine_declaration(interfaces, new.parameters[index])
                if pr:
                    new.parameters[index] = pr
                    refinement = True

        # Update identifier
        if refinement and new.identifier in __type_collection:
            if new.ret_typedef and not __type_collection[new.identifier].ret_typedef:
                __type_collection[new.identifier].ret_typedef = new.ret_typedef
            for index, pt in enumerate(__type_collection[new.identifier].params_typedef):
                if not pt and new.params_typedef[index]:
                    __type_collection[new.identifier].params_typedef[index] = new.params_typedef[index]
            new = __type_collection[new.identifier]
        elif refinement:
            __type_collection[new.identifier] = new

        if refinement:
            return new
        else:
            return None
    elif type(declaration) is Pointer and type(declaration.points) is Function:
        refined = refine_declaration(interfaces, declaration.points)
        if refined:
            ptr = refined.take_pointer
            if ptr.identifier in __type_collection:
                ptr = __type_collection[ptr.identifier]
            else:
                __type_collection[ptr.identifier] = ptr

            return ptr
        else:
            return None
    else:
        raise ValueError('Cannot clean a declaration which is not a function or an interface reference')


def _reduce_level(ast):
    if len(ast['declarator']) > 1 and \
            ('pointer' not in ast['declarator'][-1] or ast['declarator'][-1]['pointer'] == 0) and \
            ('arrays' not in ast['declarator'][-1] or len(ast['declarator'][-1]['arrays']) == 0) and \
            'function arguments' not in ast['declarator'][-1]:
        ast['declarator'].pop()
    return ast


def _take_pointer(exp, tp):
    if tp is Array or tp is Function:
        exp = '(*' + exp + ')'
    else:
        exp = '*' + exp
    return exp


def _add_parent(declaration, parent):
    global __type_collection

    if parent.identifier in __type_collection:
        parent = __type_collection[parent.identifier]
    else:
        __type_collection[parent.identifier] = parent

    if parent.identifier not in (p.identifier for p in declaration.parents):
        declaration.parents.append(parent)


class Declaration:

    @property
    def take_pointer(self):
        pointer_signature = self.to_string('a', True)
        return import_declaration(pointer_signature)

    @property
    def identifier(self):
        return self.to_string(replacement='')

    @property
    def weak_implementations(self):
        if type(self) is Pointer:
            return list(self.implementations.values()) + list(self.points.implementations.values())
        else:
            return list(self.implementations.values()) + list(self.take_pointer.implementations.values())

    @property
    def pretty_name(self):
        raise NotImplementedError

    def common_initialization(self, ast):
        self._ast = ast
        self.implementations = {}
        self.path = None
        self.parents = []
        self.typedef = None

    def add_parent(self, parent):
        _add_parent(self, parent)

    def compare(self, target):
        if type(self) is type(target):
            if self.identifier == target.identifier:
                return True
            elif self.identifier == 'void *' or target.identifier == 'void *':
                return True
        return False

    def pointer_alias(self, alias):
        if type(self) is Pointer and self.points.compare(alias):
            return self
        elif type(alias) is Pointer and self.compare(alias.points):
            return alias

        return None

    def add_implementation(self, value, path, root_type, root_value, root_sequence):
        new = Implementation(self, value, path, root_type, root_value, root_sequence)
        if new.identifier not in self.implementations:
            self.implementations[new.identifier] = new
        return new

    def nameless_type(self):
        queue = [self]
        ret = True

        while len(queue) > 0:
            tp = queue.pop()

            if isinstance(tp, Array):
                queue.append(tp.element)
            elif isinstance(tp, Pointer):
                queue.append(tp.points)
            elif (isinstance(tp, Structure) or isinstance(tp, Union) or isinstance(tp, Enum)) and not tp.name:
                ret = False
                break

        return ret

    def to_string(self, replacement='', pointer=False, typedef='none'):
        if pointer:
            replacement = _take_pointer(replacement, type(self))

        if isinstance(typedef, set) or isinstance(typedef, str):
            if self.typedef and (
                    (isinstance(typedef, set) and self.typedef in typedef) or
                    (
                        (isinstance(typedef, str) and typedef == 'all') or
                        typedef != 'none' and not self.nameless_type()
                     )):
                return "{} {}".format(self.typedef, replacement)
            else:
                return self._to_string(replacement, typedef=typedef)
        else:
            raise TypeError('Expect typedef flag to be set or str instead of {!r}'.format(type(typedef).__name__))


class Primitive(Declaration):

    def __init__(self, ast):
        self.common_initialization(ast)

    @property
    def clean_declaration(self):
        return True

    @property
    def pretty_name(self):
        pn = self._ast['specifiers']['type specifier']['name']
        return pn.replace(' ', '_')

    def _to_string(self, replacement, typedef='none'):
        if replacement == '':
            return self._ast['specifiers']['type specifier']['name']
        else:
            return "{} {}".format(self._ast['specifiers']['type specifier']['name'], replacement)


class Enum(Declaration):

    def __init__(self, ast):
        self.common_initialization(ast)
        self.enumerators = []

        if 'enumerators' in self._ast['specifiers']['type specifier']:
            self.enumerators = self._ast['specifiers']['type specifier']['enumerators']

    @property
    def name(self):
        return self._ast['specifiers']['type specifier']['name']

    @property
    def clean_declaration(self):
        return True

    @property
    def pretty_name(self):
        return 'enum_{}'.format(self.name)

    def _to_string(self, replacement, typedef='none'):
        if not self.name:
            name = '{ ' + ', '.join(self.enumerators) + ' }'
        else:
            name = self.name

        if replacement == '':
            return "enum {}".format(name)
        else:
            return "enum {} {}".format(name, replacement)


class Function(Declaration):

    def __init__(self, ast):
        self.common_initialization(ast)
        self.return_value = None
        self.parameters = []
        self.ret_typedef = None
        self.params_typedef = list()

        if 'specifiers' in self._ast['return value type'] and \
                'type specifier' in self._ast['return value type']['specifiers'] and \
                self._ast['return value type']['specifiers']['type specifier']['class'] == 'Primitive' and \
                self._ast['return value type']['specifiers']['type specifier']['name'] == 'void':
            self.return_value = None
        else:
            self.return_value, self.ret_typedef = import_declaration(None, self._ast['return value type'],
                                                                     track_typedef=True)
        for parameter in self._ast['declarator'][0]['function arguments']:
            if type(parameter) is str:
                self.parameters.append(parameter)
                self.params_typedef.append(None)
            else:
                param, typedef = import_declaration(None, parameter, track_typedef=True)
                self.parameters.append(param)
                self.params_typedef.append(typedef)

        if len(self.parameters) == 1 and type(self.parameters[0]) is Primitive and \
                self.parameters[0].pretty_name == 'void':
            self.parameters = []

    @property
    def clean_declaration(self):
        if not self.return_value.clean_declaration:
            return False
        for param in self.parameters:
            if type(param) is not str and not param.clean_declaration:
                return False
        return True

    @property
    def pretty_name(self):
        global __type_collection

        key = new_identifier()
        return 'func_{}'.format(key)

    def _to_string(self, replacement, typedef='none'):
        def filtered_typedef_param(available):
            if isinstance(typedef, set):
                return {available}
            elif available and typedef == 'complex_and_params':
                return {available}
            else:
                return typedef

        if len(self.parameters) == 0:
            replacement += '(void)'
        else:
            parameter_declarations = []
            for index, param in enumerate(self.parameters):
                if type(param) is str:
                    parameter_declarations.append(param)
                else:
                    expr = param.to_string('', typedef=filtered_typedef_param(self.params_typedef[index]))
                    parameter_declarations.append(expr)
            replacement = replacement + '(' + ', '.join(parameter_declarations) + ')'

        if self.return_value:
            replacement = self.return_value.to_string(replacement, typedef=filtered_typedef_param(self.ret_typedef))
        else:
            replacement = 'void {}'.format(replacement)
        return replacement


class Structure(Declaration):

    def __init__(self, ast):
        self.common_initialization(ast)
        self.fields = {}

        if 'fields' in self._ast['specifiers']['type specifier']:
            for declaration in sorted(self._ast['specifiers']['type specifier']['fields'],
                                      key=lambda decl: str(decl['declarator'][-1]['identifier'])):
                name = declaration['declarator'][-1]['identifier']
                if name:
                    self.fields[name] = import_declaration(None, declaration)

    @property
    def clean_declaration(self):
        return True

    @property
    def name(self):
        return self._ast['specifiers']['type specifier']['name']

    @property
    def pretty_name(self):
        if self.name:
            return 'struct_{}'.format(self.name)
        else:
            global __type_collection

            key = new_identifier()
            return 'struct_noname_{}'.format(key)

    def contains(self, target):
        return [field for field in sorted(self.fields.keys()) if self.fields[field].compare(target)]

    def weak_contains(self, target):
        return [field for field in sorted(self.fields.keys()) if self.fields[field].compare(target) or
                self.fields[field].pointer_alias(target)]

    def _to_string(self, replacement, typedef='none'):
        if not self.name:
            name = '{ ' + '; '.join([self.fields[field].to_string(field, typedef=typedef)
                                     for field in sorted(self.fields.keys())]) + \
                   '; ' + ' }'
        else:
            name = self.name

        if replacement == '':
            return "struct {}".format(name)
        else:
            return "struct {} {}".format(name, replacement)


class Union(Declaration):

    def __init__(self, ast):
        self.common_initialization(ast)
        self.fields = {}

        if 'fields' in self._ast['specifiers']['type specifier']:
            for declaration in sorted(self._ast['specifiers']['type specifier']['fields'],
                                      key=lambda decl: str(decl['declarator'][-1]['identifier'])):
                name = declaration['declarator'][-1]['identifier']
                if name:
                    self.fields[name] = import_declaration(None, declaration)

    @property
    def clean_declaration(self):
        return True

    @property
    def name(self):
        return self._ast['specifiers']['type specifier']['name']

    @property
    def pretty_name(self):
        if self._ast['specifiers']['type specifier']['name']:
            return 'union_{}'.format(self.name)
        else:
            global __type_collection

            key = new_identifier()
            return 'union_noname_{}'.format(key)

    def contains(self, target):
        return [field for field in sorted(self.fields.keys()) if self.fields[field].compare(target)]

    def weak_contains(self, target):
        return [field for field in sorted(self.fields.keys()) if self.fields[field].compare(target) or
                self.fields[field].pointer_alias(target)]

    def _to_string(self, replacement, typedef='none'):
        if not self.name:
            name = '{ ' + '; '.join([self.fields[field].to_string(field, typedef=typedef)
                                     for field in sorted(self.fields.keys())]) + \
                   '; ' + ' }'
        else:
            name = self.name

        if replacement == '':
            return "union {}".format(name)
        else:
            return "union {} {}".format(name, replacement)


class Array(Declaration):

    def __init__(self, ast):
        self.common_initialization(ast)
        self.element = None

        array = ast['declarator'][-1]['arrays'].pop()
        self.size = array['size']
        ast = _reduce_level(ast)
        self.element = import_declaration(None, ast)
        self.element.add_parent(self)

    @property
    def clean_declaration(self):
        return self.element.clean_declaration

    @property
    def pretty_name(self):
        return '{}_array'.format(self.element.pretty_name)

    def contains(self, target):
        if self.element.compare(target):
            return True
        else:
            return False

    def weak_contains(self, target):
        if self.element.compare(target) or self.element.pointer_alias(target):
            return True
        else:
            return False

    def _to_string(self, replacement, typedef='none'):
        if self.size:
            size = self.size
        else:
            size = ''
        replacement += '[{}]'.format(size)
        return self.element.to_string(replacement, typedef=typedef)


class Pointer(Declaration):

    def __init__(self, ast):
        self.common_initialization(ast)

        ast['declarator'][-1]['pointer'] -= 1
        ast = _reduce_level(ast)
        self.points = import_declaration(None, ast)
        self.points.add_parent(self)

    @property
    def clean_declaration(self):
        return self.points.clean_declaration

    def _to_string(self, replacement, typedef='none'):
        replacement = _take_pointer(replacement, type(self.points))

        return self.points.to_string(replacement, typedef=typedef)

    @property
    def pretty_name(self):
        return '{}_ptr'.format(self.points.pretty_name)


class InterfaceReference(Declaration):

    def __init__(self, ast):
        self._ast = ast
        self._identifier = None
        self.parents = []
        self.typedef = None

    @property
    def clean_declaration(self):
        return False

    @property
    def category(self):
        return self._ast['specifiers']['category']

    @property
    def short_identifier(self):
        return self._ast['specifiers']['identifier']

    @property
    def interface(self):
        return "{}.{}".format(self.category, self.short_identifier)

    @property
    def pointer(self):
        return self._ast['specifiers']['pointer']

    def _to_string(self, replacement, typedef='none'):
        if self.pointer:
            ptr = '*'
        else:
            ptr = ''

        if replacement == '':
            return '{}%{}%'.format(ptr, self.interface)
        else:
            return '{}%{}% {}'.format(ptr, self.interface, replacement)


class UndefinedReference(Declaration):

    def __init__(self, ast):
        self._ast = ast
        self.parents = []
        self.typedef = None

    @property
    def clean_declaration(self):
        return False

    @property
    def _identifier(self):
        return '$'

    def _to_string(self, replacement, typedef='none'):
        if replacement == '':
            return '$'
        else:
            return '$ {}'.format(replacement)


class Implementation:

    def __init__(self, declaration, value, file, base_container=None, base_value=None, sequence=None):
        self.base_container = base_container
        self.base_value = base_value
        self.value = value
        self.file = file
        self.sequence = sequence
        self.identifier = str([value, file, base_value, sequence])
        self.fixed_interface = None
        self.__declaration = declaration

    def adjusted_value(self, declaration):
        if self.__declaration.compare(declaration):
            return self.value
        elif self.__declaration.compare(declaration.take_pointer):
            return '*' + self.value
        elif self.__declaration.take_pointer.compare(declaration):
            return '&' + self.value
        elif type(declaration) is Pointer and type(self.__declaration) is Pointer and \
                        self.__declaration.identifier == 'void *':
            return self.value
        else:
            raise ValueError("Cannot adjust declaration '{}' to declaration '{}'".
                             format(self.__declaration.to_string('%s'), declaration.to_string('%s')))

__author__ = 'Ilja Zakharov <ilja.zakharov@ispras.ru>'
