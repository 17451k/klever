#!/usr/bin/python3

import fileinput
import json
import os
import re

import core.avtg.plugins
import core.utils


class Weaver(core.avtg.plugins.Plugin):
    def weave(self):
        self.abstract_task_desc['extra C files'] = []

        for grp in self.abstract_task_desc['grps']:
            self.logger.info('Weave in C files of group "{0}"'.format(grp['id']))

            for cc_extra_full_desc_file in grp['cc extra full desc files']:

                if 'cc full desc file' in cc_extra_full_desc_file:
                    with open(
                            os.path.join(self.conf['main working directory'], cc_extra_full_desc_file['cc full desc file']),
                            encoding='ascii') as fp:
                        cc_full_desc = json.load(fp)

                    self.logger.info('Weave in C file "{0}"'.format(cc_full_desc['in files'][0]))

                    # TODO: if several files in verification object will have the same name everything will break.
                    # Overwrite suffix because of we will obtain weaved C files.
                    cc_full_desc['out file'] = '{0}.c'.format(
                        os.path.splitext(os.path.basename(cc_full_desc['out file']))[0])

                    # Produce aspect to be weaved in.
                    if 'plugin aspects' in cc_extra_full_desc_file:
                        self.logger.info('Concatenate all aspects of all plugins together')

                        # Resulting aspect.
                        aspect = 'aspect'

                        # Get all aspects. Place RSG aspects at beginning since they can instrument entities added by
                        # aspects of other plugins while corresponding function declarations still need be at beginning of
                        # file.
                        aspects = []
                        for plugin_aspects in cc_extra_full_desc_file['plugin aspects']:
                            if plugin_aspects['plugin'] == 'RSG':
                                aspects[0:0] = plugin_aspects['aspects']
                            else:
                                aspects.extend(plugin_aspects['aspects'])

                        # Concatenate aspects.
                        with open(aspect, 'w', encoding='ascii') as fout, fileinput.input(
                                [os.path.join(self.conf['main working directory'], aspect) for aspect in aspects],
                                openhook=fileinput.hook_encoded('ascii')) as fin:
                            for line in fin:
                                fout.write(line)
                    else:
                        # Simulate resulting aspect.
                        aspect = '/dev/null'
                    self.logger.debug('Aspect to be weaved in is "{0}"'.format(aspect))

                    # This is required to get compiler (Aspectator) specific stdarg.h since kernel C files are compiled with
                    # "-nostdinc" option and system stdarg.h couldn't be used.
                    stdout = core.utils.execute(self.logger,
                                                ('aspectator', '-print-file-name=include'),
                                                collect_all_stdout=True)
                    core.utils.execute(
                        self.logger,
                        tuple([
                                  'cif',
                                  '--in', cc_full_desc['in files'][0],
                                  '--aspect', os.path.relpath(aspect,
                                                              os.path.join(self.conf['main working directory'],
                                                                           cc_full_desc['cwd'])),
                                  # Besides header files specific for rule specifications will be searched for.
                                  '--general-opts', "-I{0}".format(
                                      os.path.relpath(
                                          os.path.dirname(core.utils.find_file_or_dir(self.logger,
                                                                                      self.conf['main working directory'],
                                                                                      self.conf['rule specifications DB'])),
                                          os.path.join(self.conf['main working directory'], cc_full_desc['cwd']))),
                                  '--out', os.path.relpath(cc_full_desc['out file'],
                                                           os.path.join(self.conf['main working directory'],
                                                                        cc_full_desc['cwd'])),
                                  '--back-end', 'src',
                                  '--debug', 'DEBUG'
                              ] +
                              (['--keep'] if self.conf['keep intermediate files'] else []) +
                              ['--'] +
                              [opt.replace('"', '\\"') for opt in cc_full_desc['opts']] +
                              ['-isystem{0}'.format(stdout[0])]),
                        cwd=os.path.relpath(os.path.join(self.conf['main working directory'], cc_full_desc['cwd'])))
                    self.logger.debug('C file "{0}" was weaved in'.format(cc_full_desc['in files'][0]))

                    # In addition preprocess output files since CIF outputs a bit unpreprocessed files.
                    preprocessed_c_file = '{}.i'.format(os.path.splitext(cc_full_desc['out file'])[0])
                    core.utils.execute(self.logger,
                                       (
                                           'aspectator',
                                           '-E',
                                           '-x', 'c', cc_full_desc['out file'],
                                           '-o', preprocessed_c_file
                                       ))
                    if not self.conf['keep intermediate files']:
                        os.remove(cc_full_desc['out file'])
                    self.logger.debug('Preprocessed weaved C file was put to "{0}"'.format(preprocessed_c_file))

                    abs_paths_c_file = '{0}.abs-paths.i'.format(os.path.splitext(cc_full_desc['out file'])[0])
                    with open(preprocessed_c_file, encoding='ascii') as fp_in, open(abs_paths_c_file, 'w',
                                                                                    encoding='ascii') as fp_out:
                        # Print preprocessor header as is.
                        first_line = fp_in.readline()
                        fp_out.write(first_line)
                        for line in fp_in:
                            fp_out.write(line)
                            if line == first_line:
                                break

                        # Replace relative file paths with absolute ones for line directives in other lines.
                        for line in fp_in:
                            match = re.match(r'(# \d+ ")(.+)("\n)', line)
                            if match:
                                file = match.group(2)
                                if not os.path.isabs(file):
                                    # All relative file paths are relative to CC working directory.
                                    file = os.path.abspath(
                                        os.path.join(self.conf['main working directory'], cc_full_desc['cwd'], file))
                                fp_out.write(match.group(1) + file + match.group(3))
                            else:
                                fp_out.write(line)
                    if not self.conf['keep intermediate files']:
                        os.remove(preprocessed_c_file)
                    self.logger.debug(
                        'Preprocessed weaved C file with absolute paths was put to "{0}"'.format(abs_paths_c_file))

                    extra_c_file = {'C file': os.path.relpath(abs_paths_c_file, self.conf['main working directory'])}
                else:
                    extra_c_file = {}

                if 'rule spec id' in cc_extra_full_desc_file:
                    extra_c_file['rule spec id'] = cc_extra_full_desc_file['rule spec id']

                if 'bug kinds' in cc_extra_full_desc_file:
                    extra_c_file['bug kinds'] = cc_extra_full_desc_file['bug kinds']
                if 'automaton' in cc_extra_full_desc_file:
                    extra_c_file['automaton'] = cc_extra_full_desc_file['automaton']
                self.abstract_task_desc['extra C files'].append(extra_c_file)

        # These sections won't be reffered any more.
        del (self.abstract_task_desc['grps'])
        del (self.abstract_task_desc['deps'])

    main = weave
