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

import concurrent.futures
import json
import logging
import multiprocessing
import os
import shutil
import signal
import sys

import schedulers as schedulers
import schedulers.resource_scheduler
import utils


def executor(timeout, args):
    """
    Function just executes native scheduler client and waits until it terminates.

    :param timeout: Check that tool will exit definetly within this period of time.
    :param args: Native scheduler client execution command arguments.
    :return: It exits with the exit code returned by a client.
    """
    # todo: implement proper logging here, since usage of logging lead to hanging of threads dont know why
    ####### !!!! #######
    # I know that this is redundant code but you will not able to run clients code directly without this one!!!!
    # This is because bug in logging library. After an attempt to start the client with logging in a separate
    # process and then kill it and start it again logging will HANG and you WILL NOT able to start the client again.
    # This is known bug in logging, so do not waste your time here until it is fixed.
    ####### !!!! #######

    # Kill handler
    mypid = os.getpid()
    print('Executor {!r}: establish signal handlers'.format(mypid))
    ec = utils.execute(args, timeout=timeout)
    print('executor {!r}: Finished command: {!r}'.format(mypid, ' '.join(args)))

    # Be sure that process will exit
    os._exit(ec)


class Scheduler(schedulers.SchedulerExchange):
    """
    Implement the scheduler which is used to run tasks and jobs on this system locally.
    """
    __kv_url = None
    __node_name = None
    __cpu_cores = None
    __pool = None
    __job_conf_prototype = dict()
    __reserved = {"jobs": {}, "tasks": {}}
    __job_processes = dict()
    __task_processes = dict()
    __cached_tools_data = None
    __cached_nodes_data = None

    @staticmethod
    def scheduler_type():
        """Return type of the scheduler: 'VerifierCloud' or 'Klever'."""
        return "Klever"

    def __init__(self, conf, work_dir):
        """Do native scheduler specific initialization"""
        super(Scheduler, self).__init__(conf, work_dir)
        self.__kv_url = None
        self.__job_conf_prototype = None
        self.__pool = None
        self.__client_bin = None
        self.__manager = None
        self.init_scheduler()

    def init_scheduler(self):
        """
        Initialize scheduler completely. This method should be called both at constructing stage and scheduler
        reinitialization. Thus, all object attribute should be cleaned up and set as it is a newly created object.
        """
        super(Scheduler, self).init_scheduler()
        if "job client configuration" not in self.conf["scheduler"]:
            raise KeyError("Provide configuration property 'scheduler''job client configuration' as path to json file")
        if "controller address" not in self.conf["scheduler"]:
            raise KeyError("Provide configuration property 'scheduler''controller address'")
        self.__kv_url = self.conf["scheduler"]["controller address"]

        # Import job configuration prototype
        with open(self.conf["scheduler"]["job client configuration"], encoding="utf8") as fh:
            self.__job_conf_prototype = json.loads(fh.read())
        # Try to get configuration just to be sure that it exists
        self.__get_task_configuration()

        if "Klever Bridge" not in self.__job_conf_prototype:
            logging.debug("Add Klever Bridge settings to client job configuration")
            self.__job_conf_prototype["Klever Bridge"] = self.conf["Klever Bridge"]
        else:
            logging.debug("Use provided in configuration prototype Klever Bridge settings for jobs")
        if "common" not in self.__job_conf_prototype:
            logging.debug("Use the same 'common' options for jobs which is used for the scheduler")
        else:
            logging.debug("Use provided in configuration prototype 'common' settings for jobs")

        # Check node first time
        if "concurrent jobs" in self.conf["scheduler"]:
            concurrent_jobs = self.conf["scheduler"]["concurrent jobs"]
        else:
            concurrent_jobs = 1
        self.__manager = schedulers.resource_scheduler.ResourceManager(logging, concurrent_jobs)
        self.update_nodes()
        nodes = self.__manager.active_nodes
        if len(nodes) != 1:
            raise ValueError('Expect strictly single active connected node but {} given'.format(len(nodes)))
        else:
            self.__node_name = nodes[0]
            data = self.__manager.node_info(self.__node_name)
            self.__cpu_cores = data["CPU number"]

        # init process pull
        if "processes" not in self.conf["scheduler"]:
            raise KeyError("Provide configuration property 'scheduler''processes' to set "
                           "available number of parallel processes")
        max_processes = self.conf["scheduler"]["processes"]
        if isinstance(max_processes, float):
            max_processes = int(max_processes * self.__cpu_cores)
        if max_processes < 2:
            raise KeyError(
                "The number of parallel processes should be greater than 2 ({} is given)".format(max_processes))
        logging.info("Initialize pool with {} processes to run tasks and jobs".format(max_processes))
        if "process pool" in self.conf["scheduler"] and self.conf["scheduler"]["process pool"]:
            self.__pool = concurrent.futures.ProcessPoolExecutor(max_processes)
        else:
            self.__pool = concurrent.futures.ThreadPoolExecutor(max_processes)

        # Check client bin
        self.__client_bin = os.path.abspath(os.path.join(os.path.dirname(__file__), "../bin/scheduler-client"))

    def schedule(self, pending_tasks, pending_jobs):
        """
        Get a list of new tasks which can be launched during current scheduler iteration. All pending jobs and tasks
        should be sorted reducing the priority to the end. Each task and job in arguments are dictionaries with full
        configuration or description.

        :param pending_tasks: List with all pending tasks.
        :param pending_jobs: List with all pending jobs.
        :return: List with identifiers of pending tasks to launch and list woth identifiers of jobs to launch.
        """
        # Use resource manager to determine which jobs or task we can run t the moment.
        new_tasks, new_jobs = self.__manager.schedule(pending_tasks, pending_jobs)
        return [t[0]['id'] for t in new_tasks], [j[0]['id'] for j in new_jobs]

    def prepare_task(self, identifier, description):
        """
        Prepare a working directory before starting the solution.

        :param identifier: Verification task identifier.
        :param description: Dictionary with task description.
        :raise SchedulerException: If a task cannot be scheduled or preparation failed.
        """
        self.__prepare_solution(identifier, description, mode='task')

    def prepare_job(self, identifier, configuration):
        """
        Prepare a working directory before starting the solution.

        :param identifier: Verification task identifier.
        :param configuration: Job configuration.
        :raise SchedulerException: If a job cannot be scheduled or preparation failed.
        """
        self.__prepare_solution(identifier, configuration, mode='job')

    def solve_task(self, identifier, description, user, password):
        """
        Solve given verification task.

        :param identifier: Verification task identifier.
        :param description: Verification task description dictionary.
        :param user: User name.
        :param password: Password.
        :return: Return Future object.
        """
        logging.debug("Start solution of task {!r}".format(identifier))
        self.__manager.claim_resources(identifier, description, self.__node_name, job=False)
        return self.__pool.submit(self.__execute, self.__task_processes[identifier])

    def solve_job(self, identifier, configuration):
        """
        Solve given verification job.

        :param identifier: Job identifier.
        :param configuration: Job configuration.
        :return: Return Future object.
        """
        logging.debug("Start solution of job {!r}".format(identifier))
        self.__manager.claim_resources(identifier, configuration, self.__node_name, job=True)
        return self.__pool.submit(self.__execute, self.__job_processes[identifier])

    def flush(self):
        """Start solution explicitly of all recently submitted tasks."""
        super(Scheduler, self).flush()

    def process_task_result(self, identifier, future):
        """
        Process result and send results to the server.

        :param identifier: Task identifier string.
        :param future: Future object.
        :return: status of the task after solution: FINISHED.
        :raise SchedulerException: in case of ERROR status.
        """
        return self.__check_solution(identifier, future, mode='task')

    def process_job_result(self, identifier, future):
        """
        Process future object status and send results to the server.

        :param identifier: Job identifier string.
        :param future: Future object.
        :return: status of the job after solution: FINISHED.
        :raise SchedulerException: in case of ERROR status.
        """
        return self.__check_solution(identifier, future, mode='job')

    def cancel_job(self, identifier, future):
        """
        Stop the job solution.

        :param identifier: Verification task ID.
        :param future: Future object.
        :return: Status of the task after solution: FINISHED. Rise SchedulerException in case of ERROR status.
        :raise SchedulerException: In case of exception occured in future task.
        """
        return self.__cancel_solution(identifier, future, mode='job')

    def cancel_task(self, identifier, future):
        """
        Stop the task solution.

        :param identifier: Verification task ID.
        :param future: Future object.
        :return: Status of the task after solution: FINISHED. Rise SchedulerException in case of ERROR status.
        :raise SchedulerException: In case of exception occured in future task.
        """
        return self.__cancel_solution(identifier, future, mode='task')

    def terminate(self):
        """
        Abort solution of all running tasks and any other actions before termination.
        """
        # Submit an empty configuration
        logging.debug("Submit an empty configuration list before shutting down")
        configurations = []
        self.server.submit_nodes(configurations)

        # Terminate
        super(Scheduler, self).terminate()

        # Be sure that workers are killed
        self.__pool.shutdown(wait=False)

    def update_nodes(self):
        """
        Update statuses and configurations of available nodes and push them to the server.

        :return: Return True if nothing has changes.
        """
        # Use resource mamanger to manage resources
        cacnel_jobs, cancel_tasks = self.__manager.update_system_status(self.__kv_url)
        # todo: how to provide jobs or tasks to cancel?
        if len(cancel_tasks) > 0 or len(cacnel_jobs) > 0:
            logging.warning("Need to cancel jobs {} and tasks {} to avoid deadlocks, since resources has been "
                            "decreased".format(str(cacnel_jobs), str(cancel_tasks)))
        return self.__manager.submit_status(self.server)

    def update_tools(self):
        """
        Generate a dictionary with available verification tools and push it to the server.
        """
        data = self.__get_task_configuration()
        if not self.__cached_tools_data or str(data) != self.__cached_tools_data:
            self.__cached_tools_data = str(data)
            verification_tools = data['client']['verification tools']

            # Submit tools
            self.server.submit_tools(verification_tools)

    def __prepare_solution(self, identifier, configuration, mode='task'):
        """
        Generate a working directory, configuration files and multiprocessing Process object to be ready to just run it.

        :param identifier: Job or task identifier.
        :param configuration: A dictionary with a cinfiguration or description.
        :param mode: 'task' or 'job'.
        :raise SchedulerException: Raised if the preparation fails and task or job cannot be scheduled.
        """
        logging.info("Going to prepare execution of the {} {}".format(mode, identifier))
        args = [sys.executable, self.__client_bin]
        node_status = self.__manager.node_info(self.__node_name)
        if mode == 'task':
            subdir = 'tasks'
            client_conf = self.__get_task_configuration()
            self.__manager.check_resources(configuration, job=False)
        else:
            subdir = 'jobs'
            client_conf = self.__job_conf_prototype.copy()
            self.__manager.check_resources(configuration, job=True)
        args.append(mode)

        self.__create_work_dir(subdir, identifier)
        client_conf["Klever Bridge"] = self.conf["Klever Bridge"]
        client_conf["identifier"] = identifier
        work_dir = os.path.join(self.work_dir, subdir, identifier)
        file_name = os.path.join(work_dir, 'client.json')
        args.extend(['--file', file_name])
        self.__reserved[subdir][identifier] = dict()

        if configuration["resource limits"]["CPU time"]:
            # This is emergency timer if something will hang
            timeout = int((configuration["resource limits"]["CPU time"] * 1.5) / 100)
        else:
            timeout = None
        process = multiprocessing.Process(None, executor, identifier, [timeout, args])

        if mode == 'task':
            client_conf["Klever Bridge"] = self.conf["Klever Bridge"]
            client_conf["identifier"] = identifier
            client_conf["common"]["working directory"] = work_dir
            with open(os.path.join(work_dir, "task.json"), "w", encoding="utf8") as fp:
                json.dump(configuration, fp, ensure_ascii=False, sort_keys=True, indent=4)
            for name in ("resource limits", "verifier", "upload input files of static verifiers"):
                client_conf[name] = configuration[name]

            # Add particular
            client_conf["resource limits"]["CPU cores"] = \
                self.__get_virtual_cores(int(node_status["available CPU number"]),
                                         int(node_status["reserved CPU number"]),
                                         int(client_conf["resource limits"]["number of CPU cores"]))

            # Do verification versions check
            if client_conf['verifier']['name'] not in client_conf['client']['verification tools']:
                raise schedulers.SchedulerException(
                    'Use another verification tool or install and then specify verifier {!r} with its versions at {!r}'.
                    format(client_conf['verifier']['name'], self.conf["scheduler"]["task client configuration"]))
            if 'version' not in client_conf['verifier']:
                raise schedulers.SchedulerException('Cannot find any given {!r} version at at task description'.
                                                    format(client_conf['verifier']['name']))
            if client_conf['verifier']['version'] not in \
                    client_conf['client']['verification tools'][client_conf['verifier']['name']]:
                raise schedulers.SchedulerException(
                    'Use another version of {!r} or install given version {!r} and specify it at scheduler client '
                    'configuration {!r}'.format(client_conf['verifier']['name'], client_conf['verifier']['version'],
                                                self.conf["scheduler"]["task client configuration"]))

            self.__task_processes[identifier] = process
        else:
            klever_core_conf = configuration.copy()
            del klever_core_conf["resource limits"]
            klever_core_conf["Klever Bridge"] = self.conf["Klever Bridge"]
            klever_core_conf["working directory"] = "klever-core-work-dir"
            self.__reserved["jobs"][identifier]["configuration"] = klever_core_conf
            client_conf["common"]["working directory"] = work_dir
            client_conf["Klever Core conf"] = self.__reserved["jobs"][identifier]["configuration"]
            client_conf["resource limits"] = configuration["resource limits"]

            self.__job_processes[identifier] = process

        with open(file_name, 'w', encoding="utf8") as fp:
            json.dump(client_conf, fp, ensure_ascii=False, sort_keys=True, indent=4)

    def __check_solution(self, identifier, future, mode='task'):
        """
        Process results of the task or job solution.

        :param identifier: A job or task identifier.
        :param future: A future object.
        :return: Status after solution: FINISHED.
        :raise SchedulerException: Raised if an exception occured during the solution or if results are inconsistent.
        """
        logging.info("Going to prepare execution of the {} {}".format(mode, identifier))
        return self.__postprocess_solution(identifier, future, mode)

    def __cancel_solution(self, identifier, future, mode='task'):
        """
        Terminate process solving a process or a task, mark resources as released, clean working directory.

        :param identifier: Identifier of a job or a task.
        :param future: Future object.
        :param mode: 'task' or 'job'.
        :return: Status of the task after solution: FINISHED. Rise SchedulerException in case of ERROR status.
        :raise SchedulerException: raise if an exception occured during solution or results are inconsistent.
        """
        logging.info("Going to cancel execution of the {} {}".format(mode, identifier))
        if mode == 'task':
            process = self.__task_processes[identifier] if identifier in self.__task_processes else None
        else:
            process = self.__job_processes[identifier] if identifier in self.__job_processes else None
        if process and process.pid:
            try:
                os.kill(process.pid, signal.SIGTERM)
                logging.debug("Wait till {} {} become terminated".format(mode, identifier))
                process.join()
            except Exception as err:
                logging.warning('Cannot terminate process {}: {}'.format(process.pid, err))
        return self.__postprocess_solution(identifier, future, mode)

    def __postprocess_solution(self, identifier, future, mode):
        """
        Mark resources as released, clean the working directory.

        :param identifier: A job or task identifier
        :param mode: 'task' or 'job'.
        :raise SchedulerException: Raised if an exception occured during the solution or if results are inconsistent.
        """
        if mode == 'task':
            subdir = 'tasks'
            del self.__task_processes[identifier]
        else:
            subdir = 'jobs'
            del self.__job_processes[identifier]
        # Mark resources as released
        del self.__reserved[subdir][identifier]

        # Include logs into total scheduler logs
        work_dir = os.path.join(self.work_dir, subdir, identifier)

        # Release resources
        if "keep working directory" in self.conf["scheduler"] and self.conf["scheduler"]["keep working directory"]:
            reserved_space = int(utils.get_output('du -bs {} | cut -f1'.format(work_dir)))
        else:
            reserved_space = 0

        logging.debug('Yielding result of a future object of {} {}'.format(mode, identifier))
        try:
            if future:
                self.__manager.release_resources(identifier, self.__node_name, True if mode == 'job' else False,
                                                 reserved_space)

                result = future.result()
                logfile = "{}/client-log.log".format(work_dir)
                if os.path.isfile(logfile):
                    with open(logfile, mode='r', encoding="utf8") as f:
                        logging.debug("Scheduler client log: {}".format(f.read()))
                else:
                    raise FileNotFoundError("Cannot find Scheduler client file with logs: {!r}".format(logfile))

                errors_file = "{}/client-critical.log".format(work_dir)
                if os.path.isfile(errors_file):
                    with open(errors_file, mode='r', encoding="utf8") as f:
                        errors = f.readlines()
                else:
                    errors = []

                if len(errors) > 0:
                    error_msg = errors[-1]
                else:
                    error_msg = "Execution of {} {} finished with non-zero exit code: {}".format(mode, identifier,
                                                                                                 result)
                if len(errors) > 0 or result != 0:
                    logging.warning(error_msg)
                    raise schedulers.SchedulerException(error_msg)
            else:
                logging.debug("Seems that {} {} has not been started".format(mode, identifier))
        except Exception as err:
            error_msg = "Execution of {} {} terminated with an exception: {}".format(mode, identifier, err)
            logging.warning(error_msg)
            raise schedulers.SchedulerException(error_msg)
        finally:
            # Clean working directory
            if "keep working directory" not in self.conf["scheduler"] or \
                    not self.conf["scheduler"]["keep working directory"]:
                logging.debug("Clean task working directory {} for {}".format(work_dir, identifier))
                shutil.rmtree(work_dir)

        return "FINISHED"

    @staticmethod
    def __execute(process):
        """
        Common implementation for running of a multiprocessing process and for waiting until it terminates.

        :param process: multiprocessing.Process object.
        :raise SchedulerException: Raised if process cannot be executed or if its exit code cannot be determined.
        """
        logging.debug("Future task {!r}: Going to start a new process which will start native scheduler client".
                      format(process.name))
        process.start()
        logging.debug("Future task {!r}: get pid of the started process.".format(process.name))
        if process.pid:
            logging.debug("Future task {!r}: the pid is {!r}.".format(process.name, process.pid))
            j = process.join()
            logging.debug("Future task {!r}: join method returned {!r}.".format(process.name, str(j)))
            logging.debug("Future task {!r}: process {!r} joined, going to check its exit code".
                          format(process.name, process.pid))
            ec = process.exitcode
            logging.debug("Future task {!r}: exit code of the process {!r} is {!r}".
                          format(process.name, process.pid, str(ec)))
            if ec is not None:
                return ec
            else:
                error_msg = 'Cannot determine exit code of process {!r}'.format(process.pid)
                raise schedulers.SchedulerException(error_msg)
        else:
            raise schedulers.SchedulerException("Cannot launch process to run a job or a task")

    def __create_work_dir(self, entities, identifier):
        """
        Create the working directory for a job or a task.

        :param entities: Internal subdirectory name string.
        :param identifier: A job or task identifier string.
        """
        work_dir = os.path.join(self.work_dir, entities, identifier)
        logging.debug("Create working directory {}/{}".format(entities, identifier))
        if "keep working directory" in self.conf["scheduler"] and self.conf["scheduler"]["keep working directory"]:
            os.makedirs(work_dir.encode("utf8"), exist_ok=True)
        else:
            os.makedirs(work_dir.encode("utf8"), exist_ok=False)

    def __get_task_configuration(self):
        """
        Read the scheduler task configuration JSON file to keep it updated.

        :return: Dictionary with the updated configuration.
        """
        name = self.conf["scheduler"]["task client configuration"]
        with open(name, encoding="utf8") as fh:
            data = json.loads(fh.read())

        # Do checks
        if "client" not in data:
            raise KeyError("Specify 'client' object at task client configuration {!r}".format(name))
        if "verification tools" not in data["client"] or len(data["client"]["verification tools"]) == 0:
            raise KeyError("Specify pathes to verification tools installed as 'client''verification tools' object at "
                           "task client configuration {!r}".format(name))
        for tool in data["client"]["verification tools"]:
            if len(data["client"]["verification tools"].keys()) == 0:
                raise KeyError("Specify versions and pathes to them for installed verification tool {!r} at "
                               "'client''verification tools' object at task client configuration".format(tool))

            for version in data["client"]["verification tools"][tool]:
                if not os.path.isdir(data["client"]["verification tools"][tool][version]):
                    raise ValueError("Cannot find script {!r} for verifier {!r} of the version {!r}".
                                     format(data["client"]["verification tools"][tool][version], tool, version))

        return data

    @staticmethod
    def __get_virtual_cores(available, reserved, required):
        # First get system info
        si = utils.extract_cpu_cores_info()

        # Get keys
        pcores = sorted(si.keys())

        if available > len(pcores):
            raise ValueError('Host system has {} cores but expect {}'.format(len(pcores), available))

        cores = []
        for vcores in (si[pc] for pc in pcores[available - reserved - required:available - reserved]):
            cores.extend(vcores)

        return cores

__author__ = 'Ilja Zakharov <ilja.zakharov@ispras.ru>'
