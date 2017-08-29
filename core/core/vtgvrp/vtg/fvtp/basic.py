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
import json
import os
import re
from xml.dom import minidom
from xml.etree import ElementTree

import core.vtgvrp.vtg.fvtp.common as common


class Basic:

    def __init__(self, logger, conf, abstract_task_desc):
        """
        This is a simple strategy to generate verification tasks and corresponding benchmark descriptions. This
        particular strategy generates single verification task with maximum time limits set. It is assumed that
        the generatl algorythms is left unchanged while methods for creating different sections of the description
        can be changed.

        :param logger: Logger.
        :param conf: Dictionary
        :param abstract_task_desc: Dictionary.
        """
        self.logger = logger
        self.conf = conf
        self.abstract_task_desc = abstract_task_desc

    @property
    def verification_tasks(self):
        """
        Main routine of the strategy. It is suspicious if you need to change it, do it if you need to play with resource
        limitations or generate several tasks. This should be a generator to update archives each time before submitting
        new tasks.

        :return: List of descriptions with fully prepared tasks.
        """
        self.logger.info("Prepare single verification task for abstract task {!r}".
                         format(self.abstract_task_desc['id']))
        resource_limits = self._prepare_resource_limits()
        files = self._prepare_benchmark_description(resource_limits)
        common.prepare_verification_task_files_archive(files)
        task_description = self._prepare_task_description(resource_limits)
        if self.conf['keep intermediate files']:
            self.logger.debug('Create verification task description file "task.json"')
            with open('task.json', 'w', encoding='utf8') as fp:
                json.dump(task_description, fp, ensure_ascii=False, sort_keys=True, indent=4)
        self._cleanup()
        yield task_description, files

    def _prepare_benchmark_description(self, resource_limits):
        """
        Generate root ElementTree.Element for the benchmark description.

        :param resource_limits: Dictionary with resource limitations of the task.
        :return: ElementTree.Element.
        """
        self.logger.debug("Prepare benchmark.xml file")
        benchmark = ElementTree.Element("benchmark", {
            "tool": self.conf['verifier']['name'].lower()
        })
        if "CPU time" in resource_limits and isinstance(resource_limits["CPU time"], int):
            benchmark.set('timelimit', str(int(int(resource_limits["CPU time"]) * 0.9)))

        # Then add options
        self._prepare_run_definition(benchmark)

        # Files
        files = self._prepare_task_files(benchmark)

        # Properties
        property_file = self._prepare_property_file(benchmark)
        files.append(property_file)

        # Save the benchmark definition
        with open("benchmark.xml", "w", encoding="utf8") as fp:
            fp.write(minidom.parseString(ElementTree.tostring(benchmark)).toprettyxml(indent="    "))
        files.append("benchmark.xml")

        return files

    def _prepare_task_description(self, resource_limits):
        """
        Generate dictionary with verification task description.

        :param resource_limits: Dictionary.
        :return: Dictionary.
        """
        self.logger.debug('Prepare common verification task description')

        task_desc = {
            # Safely use id of corresponding abstract verification task since all bug kinds will be merged and each
            # abstract verification task will correspond to exactly one verificatoin task.
            'id': self.abstract_task_desc['id'],
            'job id': self.conf['identifier'],
            'format': 1,
        }
        # Copy attributes from parent job.
        for attr_name in ('priority', 'upload input files of static verifiers'):
            task_desc[attr_name] = self.conf[attr_name]

        for attr in self.abstract_task_desc['attrs']:
            attr_name = list(attr.keys())[0]
            attr_val = attr[attr_name]
            if attr_name == 'rule specification':
                self.rule_specification = attr_val

        # Use resource limits and verifier specified in job configuration.
        task_desc.update(
            {
                'verifier': {
                    'name': self.conf['verifier']['name'],
                    'version': self.conf['verifier']['version']
                },
                'resource limits': resource_limits
            }
        )

        return task_desc

    def _prepare_run_definition(self, benchmark_definition):
        """
        The function should add a new subelement with name 'rundefinition' to the XML description of the given
        benchmark. The new element should contains a list of options for the given verifier.

        :param benchmark_definition: ElementTree.Element.
        :return: None.
        """
        rundefinition = ElementTree.SubElement(benchmark_definition, "rundefinition")
        options = common.get_list_of_verifiers_options(self.logger, self.conf)

        # Add options to the XML description
        for opt in options:
            for name in opt:
                ElementTree.SubElement(rundefinition, "option", {"name": name}).text = opt[name]

    def _prepare_task_files(self, benchmark_definition):
        """
        The function prepares files and adds their names to the given benchmark definition. It should add new
        subelement 'tasks'.

        :param benchmark_definition: ElementTree.Element.
        :return: List of property file names with necessary paths to add to the final archive.
        """
        # todo: Do we need this actually?
        self._prepare_bug_kind_functions_file()

        tasks = ElementTree.SubElement(benchmark_definition, "tasks")
        if "merge source files" in self.conf:
            file = common.merge_files(self.logger, self.conf, self.abstract_task_desc)
            ElementTree.SubElement(tasks, "include").text = file
        else:
            raise NotImplementedError('BenchExec does not support verification tasks consisting from several files, '
                                      'set option "merge source files" of plugin FVTP to merge files using CIL')

        return [file]

    def _prepare_resource_limits(self):
        """
        Calculate resource limitations for the given task. In terms of this particular strategy it return just maximum
        limitations already set by a user.

        :return: Dictionary with resource limitations.
        """
        max_limitations = common.read_max_resource_limitations(self.logger, self.conf)
        return max_limitations

    def _cleanup(self):
        """
        This function delete all unnecessary files generated by the strategy. All further cleanup will be perfromed
        later.

        :return: None
        """
        if not self.conf['keep intermediate files']:
            for extra_c_file in self.abstract_task_desc['extra C files']:
                if 'C file' in extra_c_file and os.path.isfile(extra_c_file['C file']):
                    os.remove(extra_c_file['C file'])
                if 'new C file' in extra_c_file and os.path.isfile(extra_c_file['new C file']):
                    os.remove(extra_c_file['new C file'])

    def _prepare_bug_kind_functions_file(self):
        self.logger.debug('Prepare bug kind functions file "bug kind funcs.c"')

        bug_kinds = []
        for extra_c_file in self.abstract_task_desc['extra C files']:
            if 'bug kinds' in extra_c_file:
                for bug_kind in extra_c_file['bug kinds']:
                    if bug_kind not in bug_kinds:
                        bug_kinds.append(bug_kind)
        bug_kinds.sort()

        # Create bug kind function definitions that all call __VERIFIER_error() since this strategy doesn't distinguish
        # different bug kinds.
        with open('bug kind funcs.c', 'w', encoding='utf8') as fp:
            fp.write('/* http://sv-comp.sosy-lab.org/2015/rules.php */\nvoid __VERIFIER_error(void);\n')
            for bug_kind in bug_kinds:
                fp.write('void ldv_assert_{0}(int expr) {{\n\tif (!expr)\n\t\t__VERIFIER_error();\n}}\n'.format(
                    re.sub(r'\W', '_', bug_kind)))

        # Add bug kind functions file to other abstract verification task files. Absolute file path is required to get
        # absolute path references in error traces.
        self.abstract_task_desc['extra C files'].append({'C file': os.path.abspath('bug kind funcs.c')})

    def _prepare_property_file(self, benchmark_description):
        """
        Prepare a property specification file and add the corresponding element to the benchmark definition.

        :param benchmark_description: ElementTree.Element.
        :return: Path to the property file.
        """
        self.logger.info('Prepare verifier property file')

        if 'entry points' in self.abstract_task_desc:
            if len(self.abstract_task_desc['entry points']) > 1:
                raise NotImplementedError('Several entry points are not supported')

            if 'verifier specifications' in self.abstract_task_desc:
                with open('spec.prp', 'w', encoding='utf8') as fp:
                    for spec in self.abstract_task_desc['verifier specifications']:
                        fp.write('CHECK( init({0}()), {1} )\n'.format(
                            self.abstract_task_desc['entry points'][0], spec))
                property_file = 'spec.prp'

                self.logger.debug('Verifier property file was outputted to "spec.prp"')
            else:
                with open('unreach-call.prp', 'w', encoding='utf8') as fp:
                    fp.write('CHECK( init({0}()), LTL(G ! call(__VERIFIER_error())) )'.format(
                        self.abstract_task_desc['entry points'][0]))

                property_file = 'unreach-call.prp'

                self.logger.debug('Verifier property file was outputted to "unreach-call.prp"')
        else:
            raise ValueError('Verifier property file was not prepared since entry points were not specified')

        ElementTree.SubElement(benchmark_description, "propertyfile").text = property_file
        return property_file

