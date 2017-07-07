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

import glob
import json
import os
import sys
import traceback
import zipfile
import shutil
import re

from utils import execute, process_task_results, submit_task_results
from server.bridge import Server


def run_benchexec(mode, file=None, configuration=None):
    """
    This is the main routine of the native scheduler client that runs locally BenchExec for given job or task and upload
    results to Bridge.

    :param mode: Either "job" or "task".
    :param file: File with the configuration. Do not set the option alongside with the configuration one.
    :param configuration: The configuration dictionary. Do not set the option alongside with the file one.
    :return: It always exits at the end.
    """
    import logging

    if configuration and file:
        raise ValueError('Provide either file or configuration string')
    elif file:
        with open(file, encoding="utf8") as fh:
            conf = json.loads(fh.read())
    else:
        conf = configuration

    # Check common configuration
    if "common" not in conf:
        raise KeyError("Provide configuration property 'common' as an JSON-object")

    # Prepare working directory
    if "working directory" not in conf["common"]:
        raise KeyError("Provide configuration property 'common''working directory'")

    # Go to the working directory to avoid creating files elsewhere
    os.chdir(conf["common"]['working directory'])

    # Initialize logger
    # create logger
    root_logger = logging.getLogger('')
    root_logger.setLevel(logging.DEBUG)

    # create console handler and set level to debug
    ch = logging.StreamHandler(sys.stdout)
    fh = logging.FileHandler("client-log.log", mode='w', encoding='utf8')
    eh = logging.FileHandler("client-critical.log", mode='w', encoding='utf8')

    ch.setLevel(logging.INFO)
    fh.setLevel(logging.DEBUG)
    eh.setLevel(logging.WARNING)

    # create formatter
    cf_formatter = logging.Formatter('%(asctime)s %(name)s %(levelname)5s> %(message)s')
    fh_formatter = logging.Formatter('%(asctime)s (%(filename)s:%(lineno)03d) %(name)s %(levelname)5s> %(message)s')
    eh_formatter = logging.Formatter('%(message)s')

    # add formatter to ch
    ch.setFormatter(cf_formatter)
    fh.setFormatter(fh_formatter)
    eh.setFormatter(eh_formatter)

    # add ch to logger
    root_logger.addHandler(ch)
    root_logger.addHandler(fh)
    root_logger.addHandler(eh)

    logger = logging.getLogger('SchedulerClient')

    # Try to report single short line message to error log to forward it to Bridge
    server = None
    exit_code = 0
    try:
        logger.info("Going to solve a verification {}".format(mode))
        if mode == "task":
            server = Server(logger, conf["Klever Bridge"], os.curdir)
            server.register()
        elif mode not in ('job', 'task'):
            NotImplementedError("Provided mode {} is not supported by the client".format(mode))

        exit_code = solve(logger, conf, mode, server)
        logger.info("Exiting with exit code {}".format(str(exit_code)))
    except:
        logger.warning(traceback.format_exc().rstrip())
        exit_code = -1
    finally:
        if server:
            server.stop()
        if not isinstance(exit_code, int):
            exit_code = -1
        os._exit(int(exit_code))


def solve(logger, conf, mode='job', server=None):
    """
    Read configuration and either start job or task.

    :param logger: Logger object.
    :param conf: Configuration dictionary.
    :param mode: "job" or "task".
    :param server: Server object.
    :return: Exit code of BenchExec or RunExec.
    """
    logger.debug("Create configuration file \"conf.json\"")
    with open("conf.json", "w", encoding="utf8") as fp:
        json.dump(conf, fp, ensure_ascii=False, sort_keys=True, indent=4)

    if "resource limits" not in conf:
        raise KeyError("Configuration section 'resource limits' has not been provided")

    if mode == 'job':
        return solve_job(logger, conf)
    else:
        return solve_task(logger, conf, server)


def solve_task(logger, conf, server):
    """
    Perform preparation of task run and start it using BenchExec in either container or no-container mode.

    :param logger: Logger object.
    :param conf: Configuration dictionary.
    :param server: Server object.
    :return: BenchExec exit code.
    """

    # Add verifiers path
    tool = conf['verifier']['name']
    version = conf['verifier']['version']
    path = conf['client']['verification tools'][tool][version]
    logger.debug("Add {!r} of version {!r} bin location {!r} to PATH".format(tool, version, path))
    os.environ["PATH"] = "{}:{}".format(path, os.environ["PATH"])

    logger.debug("Download task")
    server.pull_task(conf["identifier"], "task files.zip")
    with zipfile.ZipFile('task files.zip') as zfp:
        zfp.extractall()

    os.makedirs("output".encode("utf8"), exist_ok=True)

    args = prepare_task_arguments(conf)
    exit_code = run(logger, args, conf, logger=logger)
    logger.info("Task solution has finished with exit code {}".format(exit_code))

    if exit_code != 0:
        # To keep the last warning exit without any exception
        server.stop()
        os._exit(int(exit_code))

    # Move tasks collected in container mode to expected place
    if "benchexec container mode" in conf['client'] and conf['client']["benchexec container mode"]:
        for entry in glob.glob(os.path.join('output', '*.files', 'cil.i', '*', '*')):
            shutil.move(entry, 'output')

    decision_results = process_task_results(logger)
    submit_task_results(logger, server, conf["identifier"], decision_results, os.path.curdir)

    return exit_code


def solve_job(logger, conf):
    """
    Perfrom preparation of job run and start it using RunExec in either container or no-container mode.

    :param logger: Logger object.
    :param conf: Donfiguration dictionary.
    :return: RunExec exit code.
    """

    # Add CIF path
    if "cif location" in conf["client"]:
        logger.debug("Add CIF bin location to path {}".format(conf["client"]["cif location"]))
        os.environ["PATH"] = "{}:{}".format(conf["client"]["cif location"], os.environ["PATH"])
        logger.debug("Current PATH content is {}".format(os.environ["PATH"]))

    # Add CIL path
    if "cil location" in conf["client"]:
        logger.debug("Add CIL bin location to path {}".format(conf["client"]["cil location"]))
        os.environ["PATH"] = "{}:{}".format(conf["client"]["cil location"], os.environ["PATH"])
        logger.debug("Current PATH content is {}".format(os.environ["PATH"]))

    # Do it to make it possible to use runexec inside Klever
    bench_exec_location = os.path.join(conf["client"]["benchexec location"])
    os.environ['PYTHONPATH'] = "{}:{}".format(os.environ['PYTHONPATH'], bench_exec_location)

    # Save Klever Core configuration to default configuration file
    with open("core.json", "w", encoding="utf8") as fh:
        json.dump(conf["Klever Core conf"], fh, ensure_ascii=False, sort_keys=True, indent=4)

    # Do this for deterministic python in job
    os.environ['PYTHONHASHSEED'] = "0"
    os.environ['PYTHONIOENCODING'] = "utf8"
    os.environ['LC_LANG'] = "en_US"
    os.environ['LC_ALL'] = "en_US.UTF8"
    os.environ['LC_C'] = "en_US.UTF8"

    args = prepare_job_arguments(conf)

    exit_code = run(logger, args, conf)
    logger.info("Job solution has finished with exit code {}".format(exit_code))

    return exit_code


def prepare_task_arguments(conf):
    """
    Prepare arguments for solution of a verification task with BenchExec.

    :param logger: Logger.
    :param conf: Configuration dictionary.
    :return: List with options.
    """

    # BenchExec arguments
    if "benchexec location" in conf["client"]:
        args = [os.path.join(conf["client"]["benchexec location"], 'bin', 'benchexec')]
    else:
        args = ['benchexec']

    if "CPU cores" in conf["resource limits"] and conf["resource limits"]["CPU cores"]:
        args.extend(["--limitCores", str(conf["resource limits"]["number of CPU cores"])])
        args.append("--allowedCores")
        args.append(','.join(list(map(str, conf["resource limits"]["CPU cores"]))))

    if conf["resource limits"]["disk memory size"] and "benchexec measure disk" in conf['client'] and\
            conf['client']["benchexec measure disk"]:
        args.extend(["--filesSizeLimit", str(conf["resource limits"]["disk memory size"]) + 'B'])

    if 'memory size' in conf["resource limits"] and conf["resource limits"]['memory size']:
        args.extend(['--memorylimit', str(conf["resource limits"]['memory size']) + 'B'])
    if 'CPU time' in conf["resource limits"] and conf["resource limits"]['CPU time']:
        args.extend(['--timelimit', str(conf["resource limits"]['CPU time'])])

    # Check container mode
    if "benchexec container mode" in conf['client'] and conf['client']["benchexec container mode"]:
        args.append('--container')

        if "benchexec container mode options" in conf['client']:
            args.extend(conf['client']["benchexec container mode options"])
    else:
        args.append('--no-container')

    args.extend(["--no-compress-results", "--outputpath", "./output/"])

    args.append("benchmark.xml")

    return args


def prepare_job_arguments(conf):
    # RunExec arguments
    if "benchexec location" in conf["client"]:
        args = [os.path.join(conf["client"]["benchexec location"], 'bin', 'runexec')]
    else:
        args = ['runexec']

    if "CPU cores" in conf["resource limits"] and conf["resource limits"]["CPU cores"]:
        args.append("--cores")
        args.append(','.join(list(map(str, conf["resource limits"]["CPU cores"]))))

    if conf["resource limits"]["disk memory size"] and "runexec measure disk" in conf['client'] and \
            conf['client']["runexec measure disk"]:
        args.extend(["--filesSizeLimit", str(conf["resource limits"]["disk memory size"]) + 'B'])

    if 'memory size' in conf["resource limits"] and conf["resource limits"]['memory size']:
        args.extend(['--memlimit', str(conf["resource limits"]['memory size']) + 'B'])
    if 'CPU time' in conf["resource limits"] and conf["resource limits"]['CPU time']:
        args.extend(['--timelimit', str(conf["resource limits"]['CPU time'])])

    # Check container mode
    if "runexec container mode" in conf['client'] and conf['client']["runexec container mode"]:
        args.append('--container')

        if "runexec container mode options" in conf['client']:
            args.extend(conf['client']["runexec container mode options"])
    else:
        args.append('--no-container')

    # Determine Klever Core script path
    if "Klever Core path" in conf["client"]:
        cmd = conf["client"]["Klever Core path"]
    else:
        cmd = os.path.join(os.path.dirname(os.path.realpath(__file__)), "../../core/bin/klever-core")
    os.environ['PYTHONPATH'] = os.path.join(os.path.dirname(cmd), os.path.pardir)

    # Do it to make it possible to use runexec inside Klever
    if "benchexec location" in conf["client"]:
        os.environ['PYTHONPATH'] = "{}:{}".format(os.environ['PYTHONPATH'], conf["client"]["benchexec location"])

    # Check existence of the file
    args.append(cmd)

    return args


def run(selflogger, args, conf, logger=None):
    """
    Run given command with or without disk space limitations.

    :param selflogger: Logger to print log of this function.
    :param args: Command arguments.
    :param conf: Configuration dictionary of the client.
    :param logger: Logger object to print log of BenchExec or RunExec.
    :return: Exit code.
    """

    if conf["resource limits"]["disk memory size"] and not \
            (("runexec measure disk" in conf['client'] and conf['client']["runexec measure disk"]) or
             ("benchexec measure disk" in conf['client'] and conf['client']["benchexec measure disk"])):
        dl = conf["resource limits"]["disk memory size"]
        if "disk checking period" not in conf['client']:
            dcp = 60
        else:
            dcp = conf['client']['disk checking period']
    else:
        dcp = None
        dl = None

    selflogger.info("Start task execution with the following options: {}".format(str(args)))
    if logger:
        return execute(args, logger=logger, disk_limitation=dl, disk_checking_period=dcp)
    else:
        with open('client-log.log', 'a', encoding="utf8") as fdo:
            ec = execute(args, logger=logger, disk_limitation=dl, disk_checking_period=dcp, stderr=fdo, stdout=fdo)

        # Runexec prints its warnings and ordinary log to STDERR, thus lets try to find warnings there and move them
        # to critical log file
        with open('client-log.log', encoding="utf8") as log:
            for line in log.readlines():
                # Warnings can be added to the file only from RunExec
                if re.search(r'WARNING', line):
                    selflogger.warning(re.search(r'WARNING - (.*)', line).group(1))
                elif re.search(r'runexec: error: .*', line):
                    selflogger.error(re.search(r'runexec: error: .*', line).group(0))

        return ec


__author__ = 'Ilja Zakharov <ilja.zakharov@ispras.ru>'
