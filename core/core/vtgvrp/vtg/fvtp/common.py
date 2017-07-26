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
import os
import re
import zipfile
import json
import core.utils


def merge_files(logger, conf):
    regex = re.compile('# 40 ".*/arm-unknown-linux-gnueabi/4.6.0/include/stdarg.h"')
    files = []

    logger.info('Merge source files by means of CIL')

    # CIL doesn't support asm goto (https://forge.ispras.ru/issues/1323).
    logger.debug('Ignore asm goto expressions')

    c_files = ()
    for extra_c_file in conf['abstract task desc']['extra C files']:
        if 'C file' not in extra_c_file:
            continue
        trimmed_c_file = '{0}.trimmed.i'.format(os.path.splitext(os.path.basename(extra_c_file['C file']))[0])
        with open(os.path.join(conf['main working directory'], extra_c_file['C file']),
                  encoding='utf8') as fp_in, open(trimmed_c_file, 'w', encoding='utf8') as fp_out:
            trigger = False

            # Specify original location to avoid references to *.trimmed.i files in error traces.
            fp_out.write('# 1 "{0}"\n'.format(extra_c_file['C file']))
            # Each such expression occupies individual line, so just get rid of them.
            for line in fp_in:

                # Asm volatile goto
                l = re.sub(r'asm volatile goto.*;', '', line)

                if not trigger and regex.match(line):
                    trigger = True
                elif trigger:
                    l = line.replace('typedef __va_list __gnuc_va_list;',
                                     'typedef __builtin_va_list __gnuc_va_list;')
                    trigger = False

                fp_out.write(l)

        extra_c_file['new C file'] = trimmed_c_file
        c_files += (trimmed_c_file, )

    args = (
               'cilly.asm.exe',
               '--printCilAsIs',
               '--domakeCFG',
               '--decil',
               '--noInsertImplicitCasts',
               # Now supported by CPAchecker frontend.
               '--useLogicalOperators',
               '--ignore-merge-conflicts',
               # Don't transform simple function calls to calls-by-pointers.
               '--no-convert-direct-calls',
               # Don't transform s->f to pointer arithmetic.
               '--no-convert-field-offsets',
               # Don't transform structure fields into variables or arrays.
               '--no-split-structs',
               '--rmUnusedInlines',
               '--out', 'cil.i',
           ) + c_files
    core.utils.execute_external_tool(logger, args=args)
    logger.debug('Merged source files was outputted to "cil.i"')

    return 'cil.i'


def get_list_of_verifiers_options(logger, conf):
    """
    Collect verifier oiptions from a user provided description, template and profile and prepare a final list of
    options. Each option is represented as a small dictionary with an option name given as a key and value provided
    as a value. The value can be None. Priority of options is the following: options given by a user
    (the most important), options provided by a profile and options from the template.

    :param logger: Logger.
    :param conf: Configuration dictionary.
    :return: List with options.
    """
    def merge(desc1, desc2):
        if "add options" not in desc1:
            desc1["add options"] = []
        if "exclude options" in desc2:
            remove = list()
            # For each excuded option
            for e in desc2["exclude options"]:
                name = list(e.keys())[0]
                value = e[name]

                # Match corresponding
                for c in desc1["add options"]:
                    if name in c and (not value or c[name] == value):
                        remove.append(c)
                        break

            # Remove objects finally
            for e in remove:
                 desc1["add options"].remove(e)

        if "add options" in desc2:
            append = []
            # Match already existing options
            for e in desc2["add options"]:
                name = list(e.keys())[0]
                value = e[name]

                # Check that there is no such option
                found = False
                for c in desc1["add options"]:
                    if name in c and (not value or c[name] == value):
                        found = True

                if not found:
                    append.append(e)

            # Add new
            desc1["add options"].extend(append)

        return desc1

    logger.debug("Import verifier profiles DB")
    try:
        verofer_profile_db = conf["verifier profiles DB"]
    except KeyError:
        raise KeyError('Set "verifier profiles DB" configuration option and provide corresponding file with '
                       'verifiers profiles containing options')
    try:
        verofer_profile_db = core.utils.find_file_or_dir(logger, conf["main working directory"], verofer_profile_db)
        with open(verofer_profile_db, 'r', encoding='utf8') as fp:
            profiles = json.loads(fp.read())
    except FileNotFoundError:
        raise FileNotFoundError("There is no verifier profiles DB file: {!r}".format(verofer_profile_db))

    logger.debug("Determine profile for the given verifier and its version")
    try:
        verifier_name = conf['VTG']['verifier']['name']
        verifier_version = conf['VTG']['verifier']['version']
        user_opts = conf['VTG']['verifier']
        profile = conf['verifier profile']
        profile_opts = profiles['profiles'][profile][verifier_name][verifier_version]
    except KeyError as err:
        raise KeyError("To run verification you need to provide: 1) both a verifer's name and version at "
                       "VTG configuration; 2) a verifier profile name at FVTP plugin configuration; 3) Create such"
                       "profile at verifiers profiles DB file and a description for the given verifier"
                       "version. The following key is actually not found: {!r}".format(err))

    logger.debug("Determine inheritance of profiles and templates")
    sets = [user_opts, profile_opts]
    try:
        while 'inherits' in sets[-1]:
            sets.append(profiles['templates'][sets[-1]['inherits']])
    except KeyError as err:
        KeyError("Profile template {!r} does not exist".format(err))

    logger.debug("Prepare final opts description")
    last = None
    while len(sets):
        if not last:
            # We know that there are at least two elements in the list
            last = sets.pop()
        new = sets.pop()
        last = merge(last, new)

    return last['add options']


def read_max_resource_limitations(logger, conf):
    """
    Get maximum resource limitations that can be set for a verification task.

    :param logger: Logger.
    :param conf: Configuration dictionary.
    :return: Dictionary.
    """
    # Read max restrictions for tasks
    restrictions_file = core.utils.find_file_or_dir(logger, conf["main working directory"], "tasks.json")
    with open(restrictions_file, 'r', encoding='utf8') as fp:
        restrictions = json.loads(fp.read())
    return restrictions


def prepare_verification_task_files_archive(files):
    with zipfile.ZipFile('task files.zip', mode='w', compression=zipfile.ZIP_DEFLATED) as zfp:
        for file in files:
            zfp.write(file)