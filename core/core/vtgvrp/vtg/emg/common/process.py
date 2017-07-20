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

from core.vtgvrp.vtg.emg.common.signature import Array, Structure, Pointer

from core.vtgvrp.vtg.emg.grammars.process import parse_process


def generate_regex_set(subprocess_name):
    dispatch_template = '\[@?{}(?:\[[^)]+\])?\]'
    receive_template = '\(!?{}(?:\[[^)]+\])?\)'
    condition_template = '<{}(?:\[[^)]+\])?>'
    subprocess_template = '{}'

    subprocess_re = re.compile('\{' + subprocess_template.format(subprocess_name) + '\}')
    receive_re = re.compile(receive_template.format(subprocess_name))
    dispatch_re = re.compile(dispatch_template.format(subprocess_name))
    condition_template_re = re.compile(condition_template.format(subprocess_name))
    regexes = [
        {'regex': subprocess_re, 'type': Subprocess},
        {'regex': dispatch_re, 'type': Dispatch},
        {'regex': receive_re, 'type': Receive},
        {'regex': condition_template_re, 'type': Condition}
    ]

    return regexes


def get_common_parameter(action, process, position):
    interfaces = [access.interface for access in process.resolve_access(action.parameters[position])
                  if access.interface]

    for peer in action.peers:
        candidates = [access.interface for access
                      in peer['process'].resolve_access(peer['subprocess'].parameters[position])
                      if access.interface]
        interfaces = set(interfaces) & set(candidates)

    if len(interfaces) == 0:
        raise RuntimeError('Need at least one common interface to send a signal')
    else:
        # Todo how to choose between several ones?
        return list(interfaces)[0]


class Access:
    def __init__(self, expression):
        self.expression = expression
        self.label = None
        self.interface = None
        self.list_access = None
        self.list_interface = None
        self.complete_list_interface = None

    def replace_with_variable(self, statement, variable):
        reg = re.compile(self.expression)
        if reg.search(statement):
            expr = self.access_with_variable(variable)
            return statement.replace(self.expression, expr)
        else:
            return statement

    def access_with_variable(self, variable):
        # Increase use counter
        variable.use += 1

        if self.label and self.label.prior_signature:
            target = self.label.prior_signature
        elif self.label and self.list_interface[-1].identifier in self.label.interfaces:
            target = self.label.get_declaration(self.list_interface[-1].identifier)
        else:
            target = self.list_interface[-1].declaration

        expression = variable.name
        accesses = self.list_access[1:]

        if len(accesses) > 0:
            candidate = variable.declaration
            previous = None
            while candidate:
                tmp = candidate

                if candidate.compare(target):
                    candidate = None
                    if type(previous) is Pointer:
                        expression = "*({})".format(expression)
                elif type(candidate) is Pointer:
                    candidate = candidate.points
                elif type(candidate) is Array:
                    candidate = candidate.element
                    expression += '[{}]'.format(accesses.pop(0))
                elif type(candidate) is Structure:
                    field = accesses.pop(0)
                    if field in candidate.fields:
                        candidate = candidate.fields[field]
                        if type(previous) is Pointer:
                            expression += '->{}'.format(field)
                        else:
                            expression += '.{}'.format(field)
                    else:
                        raise ValueError("Cannot build access from given variable '{}', something wrong with types".
                                         format(self.expression))
                else:
                    raise ValueError("Cannot build access from given variable '{}', something wrong with types".
                                     format(self.expression))

                previous = tmp

        return expression


class Label:

    def __init__(self, name, scope=None):
        self.container = False
        self.resource = False
        self.callback = False
        self.parameter = False
        self.pointer = False
        self.parameters = []
        self.file = None
        self.value = None
        self.prior_signature = None
        self.__signature_map = {}

        self.name = name
        self.scope = scope

    @property
    def interfaces(self):
        return sorted(self.__signature_map.keys())

    @property
    def declarations(self):
        if self.prior_signature:
            return [self.prior_signature]
        else:
            return sorted(self.__signature_map.values(), key=lambda d: d.identifier)

    def get_declaration(self, identifier):
        if identifier in self.__signature_map:
            return self.__signature_map[identifier]
        else:
            return None

    def set_declaration(self, identifier, declaration):
        self.__signature_map[identifier] = declaration

    def compare_with(self, label):
        if len(self.interfaces) > 0 and len(label.interfaces) > 0:
            if len(list(set(self.interfaces) & set(label.interfaces))) > 0:
                return 'equal'
            else:
                return 'different'
        elif len(label.interfaces) > 0 or len(self.interfaces) > 0:
            if (self.container and label.container) or (self.resource and label.resource) or \
                    (self.callback and label.callback):
                return 'сompatible'
            else:
                return 'different'
        elif self.prior_signature and label.prior_signature:
            my_signature = self.prior_signature
            ret = my_signature.compare_signature(label.prior_signature)
            if not ret:
                return 'different'
            else:
                return 'equal'
        else:
            raise NotImplementedError("Cannot compare label '{}' with label '{}'".format(label.name, label.name))


class Process:
    label_re = re.compile('%(\w+)((?:\.\w*)*)%')

    def __init__(self, name):
        self.name = name
        self.identifier = None
        self.labels = {}
        self.actions = {}
        self.category = None
        self.process = None
        self.headers = list()
        self.comment = None
        self.__process_ast = None
        self.__accesses = dict()
        self.allowed_implementations = dict()

    @property
    def unmatched_receives(self):
        return [self.actions[act] for act in sorted(self.actions.keys()) if type(self.actions[act]) is Receive and
                len(self.actions[act].peers) == 0]

    @property
    def unmatched_dispatches(self):
        return [self.actions[act] for act in sorted(self.actions.keys()) if type(self.actions[act]) is Dispatch and
                len(self.actions[act].peers) == 0]

    @property
    def unmatched_labels(self):
        unmatched = [self.labels[label] for label in sorted(self.labels.keys())
                     if not self.labels[label].interface and not self.labels[label].signature]
        return unmatched

    @property
    def containers(self):
        return [self.labels[name] for name in sorted(self.labels.keys()) if self.labels[name].container]

    @property
    def callbacks(self):
        return [self.labels[name] for name in sorted(self.labels.keys()) if self.labels[name].callback]

    @property
    def resources(self):
        return [self.labels[name] for name in sorted(self.labels.keys()) if self.labels[name].resource]

    def extract_label(self, string):
        name, tail = self.extract_label_with_tail(string)
        return name

    @property
    def process_ast(self):
        if not self.__process_ast:
            self.__process_ast = parse_process(self.process)
        return self.__process_ast

    @property
    def calls(self):
        return [self.actions[name] for name in sorted(self.actions.keys()) if type(self.actions[name]) is Call]

    def add_label(self, name, declaration, value=None, scope=None):
        lb = Label(name, scope)
        lb.prior_signature = declaration
        if value:
            lb.value = value

        self.labels[name] = lb
        acc = Access('%{}%'.format(name))
        acc.label = lb
        acc.list_access = [lb.name]
        self.__accesses[acc.expression] = [acc]
        return lb

    def add_condition(self, name, condition, statements, comment):
        new = Condition(name)
        self.actions[name] = new

        new.condition = condition
        new.statements = statements
        new.comment = comment
        return new

    def insert_action(self, name, after=None, before=None, instead=None):
        # Sanity checks
        if not (after or before or instead):
            raise ValueError('Choose where to insert the action')
        if not name or name not in self.actions:
            raise KeyError('Cannot rename action {!r} in process {!r} because it does not exist'.
                           format(name, self.name))
        if instead:
            # Delete old subprocess
            del self.actions[name]

        # Replace action entries
        processes = [self]
        processes.extend(
            [self.actions[name] for name in sorted(self.actions.keys()) if type(self.actions[name]) is Subprocess])
        regexes = generate_regex_set(name)
        for process in processes:
            for regex in regexes:
                m = regex['regex'].search(process.process)
                if m:
                    # Replace signal entries
                    curr_expr = m.group(0)
                    if before:
                        next_expr = "{}.{}".format(before, curr_expr)
                    elif after:
                        next_expr = "{}.{}".format(curr_expr, after)
                    else:
                        next_expr = instead

                    process.process = process.process.replace(curr_expr, next_expr)
                    break

    def rename_action(self, name, new_name):
        if name not in self.actions:
            raise KeyError('Cannot rename subprocess {} in process {} because it does not exist'.
                           format(name, self.name))

        action = self.actions[name]
        action.name = new_name

        # Delete old subprocess
        del self.actions[name]

        # Set new subprocess
        self.actions[action.name] = action

        # Replace subprocess entries
        processes = [self]
        processes.extend(
            [self.actions[name] for name in sorted(self.actions.keys()) if isinstance(self.actions[name], Subprocess)])
        regexes = generate_regex_set(name)
        for process in processes:
            for regex in regexes:
                if regex['regex'].search(process.process):
                    # Replace signal entries
                    old_match = regex['regex'].search(process.process).group()
                    new_match = old_match.replace(name, new_name)
                    process.process = process.process.replace(old_match, new_match)

    def extract_label_with_tail(self, string):
        if self.label_re.fullmatch(string):
            name = self.label_re.fullmatch(string).group(1)
            tail = self.label_re.fullmatch(string).group(2)
            if name not in self.labels:
                raise ValueError("Cannot extract label name from string '{}': no such label".format(string))
            else:
                return self.labels[name], tail
        else:
            raise ValueError('Cannot extract label from access {} in process {}'.format(string, format(string)))

    def establish_peers(self, process):
        peers = self.get_available_peers(process)
        for signals in peers:
            for index in range(len(self.actions[signals[0]].parameters)):
                label1 = self.extract_label(self.actions[signals[0]].parameters[index])
                label2 = process.extract_label(process.actions[signals[1]].parameters[index])

                if len(label1.interfaces) > 0 and not label2.prior_signature and not label2.parameter:
                    for intf in label1.interfaces:
                        if label1.get_declaration(intf) and (intf not in label2.interfaces or
                                                             not label2.get_declaration(intf)):
                            label2.set_declaration(intf, label1.get_declaration(intf))
                if len(label2.interfaces) > 0 and not label1.prior_signature and not label1.parameter:
                    for intf in label2.interfaces:
                        if label2.get_declaration(intf) and (intf not in label1.interfaces or
                                                             not label1.get_declaration(intf)):
                            label1.set_declaration(intf, label2.get_declaration(intf))
                if label1.prior_signature and not label2.prior_signature and len(label2.interfaces) == 0:
                    label2.prior_signature = label1.prior_signature
                if label2.prior_signature and not label1.prior_signature and len(label1.interfaces) == 0:
                    label1.prior_signature = label2.prior_signature

            self.actions[signals[0]].peers.append(
            {
                'process': process,
                'subprocess': process.actions[signals[1]]
            })
            process.actions[signals[1]].peers.append(
            {
                'process': self,
                'subprocess': self.actions[signals[0]]
            })

    def get_available_peers(self, process):
        ret = []

        # Match dispatches
        for dispatch in self.unmatched_dispatches:
            for receive in process.unmatched_receives:
                match = self.__compare_signals(process, dispatch, receive)
                if match:
                    ret.append([dispatch.name, receive.name])

        # Match receives
        for receive in self.unmatched_receives:
            for dispatch in process.unmatched_dispatches:
                match = self.__compare_signals(process, receive, dispatch)
                if match:
                    ret.append([receive.name, dispatch.name])

        return ret

    def accesses(self, accesses=None, exclude=list(), no_labels=False):
        if not accesses:
            accss = dict()
            
            if not self.__accesses or len(exclude) > 0 or no_labels:
                # Collect all accesses across process subprocesses
                for action in [self.actions[name] for name in sorted(self.actions.keys())]:
                    tp = type(action)
                    if tp not in exclude:
                        if type(action) is Call or type(action) is CallRetval and action.callback:
                            accss[action.callback] = []
                        if type(action) is Call:
                            for index in range(len(action.parameters)):
                                accss[action.parameters[index]] = []
                        if type(action) is Receive or type(action) is Dispatch:
                            for index in range(len(action.parameters)):
                                accss[action.parameters[index]] = []
                        if type(action) is CallRetval and action.retlabel:
                            accss[action.retlabel] = []
                        if type(action) is Condition:
                            for statement in action.statements:
                                for match in self.label_re.finditer(statement):
                                    accss[match.group()] = []
                        if action.condition:
                            for statement in action.condition:
                                for match in self.label_re.finditer(statement):
                                    accss[match.group()] = []

                # Add labels with interfaces
                if not no_labels:
                    for label in [self.labels[name] for name in sorted(self.labels.keys())]:
                        access = '%{}%'.format(label.name)
                        if access not in accss:
                            accss[access] = []

                if not self.__accesses and len(exclude) == 0 and not no_labels:
                    self.__accesses = accss
            else:
                accss = self.__accesses
            
            return accss
        else:
            self.__accesses = accesses

    def resolve_access(self, access, interface=None):
        if type(access) is Label:
            string = '%{}%'.format(access.name)
        elif type(access) is str:
            string = access
        else:
            raise TypeError('Unsupported access token')

        if not interface:
            return self.__accesses[string]
        else:
            return [acc for acc in sorted(self.__accesses[string], key=lambda acc: acc.interface.identifier)
                    if acc.interface and acc.interface.identifier == interface][0]

    def __compare_signals(self, process, first, second):
        if first.name == second.name and len(first.parameters) == len(second.parameters):
            match = True
            for index in range(len(first.parameters)):
                label = self.extract_label(first.parameters[index])
                if not label:
                    raise ValueError("Provide label in subprocess '{}' at position '{}' in process '{}'".
                                     format(first.name, index, self.name))
                pair = process.extract_label(second.parameters[index])
                if not pair:
                    raise ValueError("Provide label in subprocess '{}' at position '{}'".
                                     format(second.name, index, process.name))

                ret = label.compare_with(pair)
                if ret != "сompatible" and ret != "equal":
                    match = False
                    break
            return match
        else:
            return False

    def get_implementation(self, access):
        if access.interface:
            if self.allowed_implementations[access.expression][access.interface.identifier] != '':
                return self.allowed_implementations[access.expression][access.interface.identifier]
            else:
                return False
        else:
            return None


class Action:

    def __init__(self, name):
        self.name = name
        self.comment = None


class Subprocess(Action):

    def __init__(self, name):
        super().__init__(name)
        self.process = None
        self.condition = None
        self.__process_ast = None

    @property
    def process_ast(self):
        if not self.__process_ast:
            self.__process_ast = parse_process(self.process)
        return self.__process_ast


class Dispatch(Action):

    def __init__(self, name):
        super().__init__(name)
        self.condition = None
        self.parameters = []
        self.broadcast = False
        self.peers = []


class Receive(Action):

    def __init__(self, name):
        super().__init__(name)
        self.parameters = []
        self.condition = None
        self.replicative = False
        self.peers = []


class Call(Action):

    def __init__(self, name):
        super().__init__(name)
        self.condition = None
        self.callback = None
        self.parameters = []
        self.retlabel = None
        self.pre_call = []
        self.post_call = []


class CallRetval(Action):

    def __init__(self, name):
        super().__init__(name)
        self.parameters = []
        self.callback = None
        self.retlabel = None
        self.condition = None


class Condition(Action):

    def __init__(self, name):
        super().__init__(name)
        self.statements = []
        self.condition = None


__author__ = 'Ilja Zakharov <ilja.zakharov@ispras.ru>'