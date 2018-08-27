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

import fileinput
import os
import clade.interface as clade_api

import core.vtg.utils
import core.utils
import core.vtg.plugins


class ASE(core.vtg.plugins.Plugin):
    def extract_argument_signatures(self):
        if 'request aspects' not in self.conf:
            raise KeyError('There is not mandatory option "request aspects"')

        if not self.conf['request aspects']:
            raise KeyError(
                'Value of option "request aspects" is not mandatory JSON object with request aspects as keys')

        clade_api.setup(self.conf['Clade']['base'])
        storage = clade_api.FileStorage()

        self.request_arg_signs(storage)

        if 'template context' not in self.abstract_task_desc:
            self.abstract_task_desc['template context'] = {}

        for request_aspect in self.conf['request aspects']:
            arg_signs_file = os.path.splitext(os.path.splitext(os.path.basename(request_aspect))[0])[0]

            arg_signs = None

            if os.path.isfile(arg_signs_file):
                self.logger.info('Process obtained argument signatures from file "{0}"'.format(arg_signs_file))
                # We could obtain the same argument signatures, so remove duplicates.
                with open(arg_signs_file, encoding='utf8') as fp:
                    arg_signs = set(fp.read().splitlines())
                self.logger.debug('Obtain following argument signatures "{0}"'.format(arg_signs))

            # Convert each argument signature (that is represented as C identifier) into:
            # * the same identifier but with leading "_" for concatenation with other identifiers ("_" allows to
            #   separate these idetifiers visually more better in rendered templates, while in original templates they
            #   are already separated quite well by template syntax, besides, we can generate models and aspects without
            #   agrument signatures at all on the basis of the same templates)
            # * more nice text representation for notes to be shown to users.
            self.abstract_task_desc['template context'][arg_signs_file] = {
                arg_signs_file + '_arg_signs':
                    [
                        {'id': '_{0}'.format(arg_sign), 'text': ' "{0}"'.format(arg_sign)}
                        for arg_sign in sorted(arg_signs)
                    ] if arg_signs else [{'id': '', 'text': ''}],
                arg_signs_file + '_arg_sign_patterns':
                    ['_$arg_sign{0}'.format(i) if arg_signs else '' for i in range(10)]
            }

    def request_arg_signs(self, storage):
        self.logger.info('Request argument signatures')

        for request_aspect in self.conf['request aspects']:
            request_aspect = core.utils.find_file_or_dir(self.logger, self.conf['main working directory'],
                                                         request_aspect)
            self.logger.debug('Request aspect is "{0}"'.format(request_aspect))

            # This is required to get compiler (Aspectator) specific stdarg.h since kernel C files are compiled with
            # "-nostdinc" option and system stdarg.h couldn't be used.
            aspectator_search_dir = '-isystem' + core.utils.execute(self.logger,
                                                                    ('aspectator', '-print-file-name=include'),
                                                                    collect_all_stdout=True)[0]

            for grp in self.abstract_task_desc['grps']:
                self.logger.info('Request argument signatures for C files of group "{0}"'.format(grp['id']))

                for extra_cc in grp['Extra CCs']:
                    self.logger.info('Request argument signatures for C file "{0}"'.format(extra_cc['in file']))

                    cc = clade_api.get_cc(extra_cc['CC'])
                    cc['opts'] = clade_api.get_cc_opts(extra_cc['CC'])

                    env = dict(os.environ)
                    env['LDV_ARG_SIGNS_FILE'] = os.path.realpath(
                        os.path.splitext(os.path.splitext(os.path.basename(request_aspect))[0])[0])

                    # Add plugin aspects produced thus far (by EMG) since they can include additional headers for which
                    # additional argument signatures should be extracted. Like in Weaver.
                    if 'plugin aspects' in extra_cc:
                        self.logger.info('Concatenate all aspects of all plugins together')

                        # Resulting request aspect.
                        aspect = '{0}.aspect'.format(core.utils.unique_file_name(os.path.splitext(os.path.basename(
                            cc['out']))[0], '.aspect'))

                        # Get all aspects. Place original request aspect at beginning since it can instrument entities
                        # added by aspects of other plugins while corresponding function declarations still need be at
                        # beginning of file.
                        aspects = [os.path.relpath(request_aspect, self.conf['main working directory'])]
                        for plugin_aspects in extra_cc['plugin aspects']:
                            aspects.extend(plugin_aspects['aspects'])

                        # Concatenate aspects.
                        with open(aspect, 'w', encoding='utf8') as fout, fileinput.input(
                                [os.path.join(self.conf['main working directory'], aspect) for aspect in aspects],
                                openhook=fileinput.hook_encoded('utf8')) as fin:
                            for line in fin:
                                fout.write(line)
                    else:
                        aspect = request_aspect

                    core.utils.execute(self.logger,
                                       tuple(['cif',
                                              '--in', extra_cc['in file'],
                                              '--aspect', os.path.realpath(aspect),
                                              '--stage', 'instrumentation',
                                              # TODO: issues like in Weaver.
                                              '--out', os.path.realpath('{0}.c'.format(core.utils.unique_file_name(
                                               os.path.splitext(os.path.basename(cc['out']))[0], '.c.aux'))),
                                              '--debug', 'DEBUG'] +
                                             (['--keep'] if self.conf['keep intermediate files'] else []) +
                                             ['--'] +
                                             core.utils.prepare_cif_opts(self.conf, cc['opts'], storage.storage_dir) +
                                             [
                                                 # Besides header files specific for requirements will be
                                                 # searched for.
                                                 '-I' + os.path.realpath(os.path.dirname(
                                                     self.conf['requirements DB'])),
                                                 aspectator_search_dir
                                             ]),
                                       env,
                                       cwd=storage.storage_dir + cc['cwd'],
                                       filter_func=core.vtg.utils.CIFErrorFilter())

    main = extract_argument_signatures
