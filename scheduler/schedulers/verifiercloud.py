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
import logging
import os
import re
import shutil
import sys
import glob
import uuid
import xml.etree.ElementTree as ET
from xml.dom import minidom
import schedulers as schedulers
import utils


class Run:
    """Class represents VerifierCloud scheduler for task forwarding to the cloud."""

    def __init__(self, work_dir, description):
        """
        Initialize Run object.

        :param work_dir: A path to the directory from which paths given in description are relative.
        :param description: Dictionary with a task description.
        :param user: A VerifierCloud username.
        :param password: A VerifierCloud password.
        """
        self.branch = None
        self.revision = None
        self.version = None
        self.options = []

        # Check verifier
        if description["verifier"]["name"] != "CPAchecker":
            raise ValueError("VerifierCloud can use only 'CPAchecker' tool, but {} is given instead".format(
                description["verifier"]["name"]))
        else:
            self.tool = "CPAchecker"

        if "version" in description["verifier"]:
            self.version = description["verifier"]["version"]
            if ":" in self.version:
                self.branch, self.revision = self.version.split(':')
            else:
                self.revision = self.version

        # Check priority
        if description["priority"] not in ["LOW", "IDLE"]:
            logging.warning("Task {} has priority higher than LOW".format(description["id"]))
            self.priority = "LOW"
        self.priority = description["priority"]

        # Set limits
        self.limits = {
            "memlimit": int(description["resource limits"]["memory size"]),  # In bytes.
            "timelimit": int(description["resource limits"]["CPU time"] / 1000)
        }

        # Check optional limits
        if "number of CPU cores" in description["resource limits"]:
            self.limits["corelimit"] = int(description["resource limits"]["number of CPU cores"])
        if "CPU model" in description["resource limits"]:
            self.cpu_model = description["resource limits"]["CPU model"]
        else:
            self.cpu_model = None

        # Parse Benchmark XML
        with open(os.path.join(work_dir, 'benchmark.xml'), encoding="utf8") as fp:
            result = ET.parse(fp).getroot()
            # Expect single run definition
            if len(result.findall("rundefinition")) != 1:
                raise ValueError('Expect a single rundefinition tag')
            opt_tags = result.findall("rundefinition")[0].findall('option')
            for tag in opt_tags:
                if 'name' in tag.attrib:
                    self.options.append(tag.get('name'))
                if tag.text:
                    self.options.append(tag.text)

        # Set source, property and specification files if so
        # Some property file should be always specified
        if len(result.findall("propertyfile")) != 1:
            raise ValueError('Expect a single property file given with "propertyfile" tag')
        self.propertyfile = os.path.join(work_dir, result.findall("propertyfile")[0].text)
        if len(result.findall('tasks')) != 1 or len(result.findall('tasks')[0].findall('include')) != 1:
            raise ValueError('Expect a single task with a single included file')
        self.sourcefiles = [os.path.join(work_dir, result.findall('tasks')[0].findall('include')[0].text)]

    @staticmethod
    def user_pwd(user, password):
        """
        Provide a user and a password in the format expected by VerifierCloud adapter library.

        :param user: String
        :param password: String.
        :return: String.
        """
        return "{}:{}".format(user, password)


class Scheduler(schedulers.SchedulerExchange):
    """
    Implement scheduler which is based on VerifierCloud web-interface. The scheduler forwards task to the remote
    VerifierCloud and fetch results from there.
    """

    wi = None

    def __init__(self, conf, work_dir):
        """Do VerifierCloud specific initialization"""
        super(Scheduler, self).__init__(conf, work_dir)
        self.wi = None
        self.__tasks = None
        self.init_scheduler()

    def init_scheduler(self):
        """
        Initialize scheduler completely. This method should be called both at constructing stage and scheduler
        reinitialization. Thus, all object attribute should be cleaned up and set as it is a newly created object.
        """
        super(Scheduler, self).init_scheduler()

        # Perform sanity checks before initializing scheduler
        if "web-interface address" not in self.conf["scheduler"] or not self.conf["scheduler"]["web-interface address"]:
            raise KeyError("Provide VerifierCloud address within configuration property "
                           "'scheduler''Web-interface address'")

        web_client_location = os.path.join(self.conf["scheduler"]["web client location"])
        logging.debug("Add to PATH web client location {0}".format(web_client_location))
        sys.path.append(web_client_location)
        from webclient import WebInterface
        self.wi = WebInterface(self.conf["scheduler"]["web-interface address"], None)

        self.__tasks = dict()

    @staticmethod
    def scheduler_type():
        """Return type of the scheduler: 'VerifierCloud' or 'Klever'."""
        return "VerifierCloud"

    def schedule(self, pending_tasks, pending_jobs):
        """
        Get a list of new tasks which can be launched during current scheduler iteration. All pending jobs and tasks
        should be sorted reducing the priority to the end. Each task and job in arguments are dictionaries with full
        configuration or description.

        :param pending_tasks: List with all pending tasks.
        :param pending_jobs: List with all pending jobs.
        :return: List with identifiers of pending tasks to launch and list woth identifiers of jobs to launch.
        """
        return [pending_tasks["id"] for pending_tasks in pending_tasks], []

    def prepare_task(self, identifier, description):
        """
        Prepare a working directory before starting the solution.

        :param identifier: Verification task identifier.
        :param description: Dictionary with task description.
        :raise SchedulerException: If a task cannot be scheduled or preparation failed.
        """
        # Prepare working directory
        task_work_dir = os.path.join(self.work_dir, "tasks", identifier)
        task_data_dir = os.path.join(task_work_dir, "data")
        logging.debug("Make directory for the task to solve {0}".format(task_data_dir))
        os.makedirs(task_data_dir.encode("utf8"), exist_ok=True)

        # Pull the task from the Verification gateway
        archive = os.path.join(task_work_dir, "task.zip")
        logging.debug("Pull from the verification gateway archive {}".format(archive))
        self.server.pull_task(identifier, archive)
        logging.debug("Unpack archive {} to {}".format(archive, task_data_dir))
        shutil.unpack_archive(archive, task_data_dir)

        # TODO: Add more exceptions handling to make code more reliable
        with open(os.path.join(os.path.join(self.work_dir, "tasks", identifier), "task.json"), "w",
                  encoding="utf8") as fp:
            json.dump(description, fp, ensure_ascii=False, sort_keys=True, indent=4)

        # Prepare command to submit
        logging.debug("Prepare arguments of the task {}".format(identifier))
        task_data_dir = os.path.join(self.work_dir, "tasks", identifier, "data")
        try:
            run = Run(task_data_dir, description)
        except Exception as err:
            raise schedulers.SchedulerException('Cannot prepare task description on base of given benchmark.xml: {}'.
                                                format(err))
        self.__tasks[identifier] = run

    def prepare_job(self, identifier, configuration):
        """
        Prepare a working directory before starting the solution.

        :param identifier: Verification task identifier.
        :param configuration: Job configuration.
        :raise SchedulerException: If a job cannot be scheduled or preparation failed.
        """
        # Cannot be called
        raise NotImplementedError("VerifierCloud cannot handle jobs.")

    def solve_task(self, identifier, description, user, password):
        """
        Solve given verification task.

        :param identifier: Verification task identifier.
        :param description: Verification task description dictionary.
        :param user: User name.
        :param password: Password.
        :return: Return Future object.
        """
        # Submit command
        logging.info("Submit the task {0}".format(identifier))
        run = self.__tasks[identifier]
        return self.wi.submit(run=run,
                              limits=run.limits,
                              cpu_model=run.cpu_model,
                              result_files_pattern='output/**',
                              priority=run.priority,
                              user_pwd=run.user_pwd(user, password),
                              svn_branch=run.branch,
                              svn_revision=run.revision,
                              meta_information=json.dumps({'Verification tasks produced by Klever': None}))

    def solve_job(self, identifier, configuration):
        """
        Solve given verification job.

        :param identifier: Job identifier.
        :param configuration: Job configuration.
        :return: Return Future object.
        """
        raise NotImplementedError('VerifierCloud cannot start jobs.')

    def flush(self):
        """Start solution explicitly of all recently submitted tasks."""
        self.wi.flush_runs()

    def process_task_result(self, identifier, future):
        """
        Process result and send results to the server.

        :param identifier: Task identifier string.
        :param future: Future object.
        :return: status of the task after solution: FINISHED.
        :raise SchedulerException: in case of ERROR status.
        """
        run = self.__tasks[identifier]
        del self.__tasks[identifier]

        task_work_dir = os.path.join(self.work_dir, "tasks", identifier)
        solution_file = os.path.join(task_work_dir, "solution.zip")
        logging.debug("Save solution to the disk as {}".format(solution_file))
        if future.result():
            with open(solution_file, 'wb') as sa:
                sa.write(future.result())
        else:
            error_msg = "Task {} has been finished but no data has been received: {}".format(identifier, err)
            logging.warning(error_msg)
            raise schedulers.SchedulerException(error_msg)

        # Unpack results
        task_solution_dir = os.path.join(task_work_dir, "solution")
        logging.debug("Make directory for the solution to extract {0}".format(task_solution_dir))
        os.makedirs(task_solution_dir.encode("utf8"), exist_ok=True)
        logging.debug("Extract results from {} to {}".format(solution_file, task_solution_dir))
        shutil.unpack_archive(solution_file, task_solution_dir)
        # Process results and convert RunExec output to result description
        # TODO: what will happen if there will be several input files?
        # Simulate BenchExec behaviour when one input file is provided.
        os.makedirs(os.path.join(task_solution_dir, "output", "benchmark.logfiles").encode("utf8"), exist_ok=True)
        shutil.move(os.path.join(task_solution_dir, 'output.log'),
                    os.path.join(task_solution_dir, "output", "benchmark.logfiles",
                                 "{}.log".format(os.path.basename(run.sourcefiles[0]))))

        try:
            solution_identifier, solution_description = \
                self.__extract_description(task_solution_dir)
            logging.debug("Successfully extracted solution {} for task {}".format(solution_identifier, identifier))
        except Exception as err:
            logging.warning("Cannot extract results from a solution: {}".format(err))
            raise err

        # Make fake BenchExec XML report
        self.__make_fake_benchexec(solution_description, run,
                                   os.path.join(task_work_dir, 'solution', 'output',
                                                "benchmark.results.xml"))

        # Make archive
        solution_archive = os.path.join(task_work_dir, "solution")
        logging.debug("Make archive {} with a solution of the task {}.zip".format(solution_archive, identifier))
        shutil.make_archive(solution_archive, 'zip', task_solution_dir)
        solution_archive += ".zip"

        # Push result
        logging.debug("Upload solution archive {} of the task {} to the verification gateway".format(solution_archive,
                                                                                                     identifier))
        try:
            utils.submit_task_results(logging, self.server, identifier, solution_description,
                                      os.path.join(task_work_dir, "solution"))
        except Exception as err:
            error_msg = "Cannot submit solution results of task {}: {}".format(identifier, err)
            logging.warning(error_msg)
            raise schedulers.SchedulerException(error_msg)

        if "keep working directory" not in self.conf["scheduler"] or \
                not self.conf["scheduler"]["keep working directory"]:
            logging.debug("Clean task working directory {} for {}".format(task_work_dir, identifier))
            shutil.rmtree(task_work_dir)

        logging.debug("Task {} has been processed successfully".format(identifier))
        return "FINISHED"

    def process_job_result(self, identifier, future):
        """
        Process future object status and send results to the server.

        :param identifier: Job identifier string.
        :param future: Future object.
        :return: status of the job after solution: FINISHED.
        :raise SchedulerException: in case of ERROR status.
        """
        raise NotImplementedError('There cannot be any running jobs in VerifierCloud')

    def cancel_job(self, identifier, future):
        """
        Stop the job solution.

        :param identifier: Verification task ID.
        :param future: Future object.
        :return: Status of the task after solution: FINISHED. Rise SchedulerException in case of ERROR status.
        :raise SchedulerException: In case of exception occured in future task.
        """
        raise NotImplementedError('VerifierCloud cannot have running jobs, so they cannot be cancelled')

    def cancel_task(self, identifier, future):
        """
        Stop the task solution.

        :param identifier: Verification task ID.
        :param future: Future object.
        :return: Status of the task after solution: FINISHED. Rise SchedulerException in case of ERROR status.
        :raise SchedulerException: In case of exception occured in future task.
        """
        logging.debug("Cancel task {}".format(identifier))
        # todo: Implement proper task cancellation
        super(Scheduler, self).cancel_task(identifier)
        task_work_dir = os.path.join(self.work_dir, "tasks", identifier)
        shutil.rmtree(task_work_dir)
        if identifier in self.__tasks:
            del self.__tasks[identifier]

    def terminate(self):
        """
        Abort solution of all running tasks and any other actions before termination.
        """
        logging.info("Terminate all runs")
        self.wi.shutdown()

    def update_nodes(self, wait_controller=False):
        """
        Update statuses and configurations of available nodes and push them to the server.

        :param wait_controller: Ignore KV fails until it become working.
        :return: Return True if nothing has changes.
        """
        return super(Scheduler, self).update_nodes()

    def update_tools(self):
        """
        Generate a dictionary with available verification tools and push it to the server.
        """
        # TODO: Implement proper revisions sending
        return

    @staticmethod
    def __extract_description(solution_dir):
        """
        Get directory with BenchExec output and extract results from there saving them to JSON file according to provided
        path.
        :param solution_dir: Path with BenchExec output.
        :return: Identifier string of the solution.
        """
        identifier = str(uuid.uuid4())
        description = {
            "id": identifier,
            "resources": {},
            "comp": {}
        }

        # Import description
        desc_file = os.path.join(solution_dir, "runDescription.txt")
        logging.debug("Import description from the file {}".format(desc_file))
        description["desc"] = ""
        if os.path.isfile(desc_file):
            with open(desc_file, encoding="utf8") as di:
                for line in di:
                    key, value = line.strip().split("=")
                    if key == "tool":
                        description["desc"] += value
                    elif key == "revision":
                        description["desc"] += " {}".format(value)
        else:
            raise FileNotFoundError("There is no solution file {}".format(desc_file))

        # Import general information
        general_file = os.path.join(solution_dir, "runInformation.txt")
        logging.debug("Import general information from the file {}".format(general_file))
        termination_reason = None
        number = re.compile("(\d.*\d)")
        if os.path.isfile(general_file):
            with open(general_file, encoding="utf8") as gi:
                for line in gi:
                    key, value = line.strip().split("=", maxsplit=1)
                    if key == "terminationreason":
                        termination_reason = value
                    elif key == "command":
                        description["comp"]["command"] = value
                    elif key == "exitsignal":
                        description["signal num"] = int(value)
                    elif key == "returnvalue":
                        description["return value"] = int(value)
                    elif key == "walltime":
                        sec = number.match(value).group(1)
                        if sec:
                            description["resources"]["wall time"] = int(float(sec) * 1000)
                        else:
                            logging.warning("Cannot properly extract wall time from {}".format(general_file))
                    elif key == "cputime":
                        sec = number.match(value).group(1)
                        if sec:
                            description["resources"]["CPU time"] = int(float(sec) * 1000)
                        else:
                            logging.warning("Cannot properly extract CPU time from {}".format(general_file))
                    elif key == "memory":
                        mem_bytes = number.match(value).group(1)
                        if mem_bytes:
                            description["resources"]["memory size"] = int(mem_bytes)
                        else:
                            logging.warning("Cannot properly extract exhausted memory from {}".format(general_file))
                    elif key == "coreLimit":
                        cores = int(value)
                        description["resources"]["coreLimit"] = cores
        else:
            raise FileNotFoundError("There is no solution file {}".format(general_file))

        # Set final status
        if termination_reason:
            if termination_reason == "cputime":
                description["status"] = "TIMEOUT"
            elif termination_reason == "memory":
                description["status"] = 'OUT OF MEMORY'
            else:
                raise ValueError("Unsupported termination reason {}".format(termination_reason))
        elif "signal num" in description:
            description["status"] = "killed by signal"
        elif "return value" in description:
            if description["return value"] == 0:
                if glob.glob(os.path.join(solution_dir, "output", "witness.*.graphml")):
                    description["status"] = "false"
                else:
                    description["status"] = "true"
            else:
                description["status"] = "unknown"
        else:
            raise ValueError("Cannot determine termination reason according to the file {}".format(general_file))

        # Import Host information
        host_file = os.path.join(solution_dir, "hostInformation.txt")
        logging.debug("Import host information from the file {}".format(host_file))
        lv_re = re.compile("Linux\s(\d.*)")
        if os.path.isfile(host_file):
            with open(host_file, encoding="utf8") as hi:
                for line in hi:
                    key, value = line.strip().split("=", maxsplit=1)
                    if key == "name":
                        description["comp"]["node name"] = value
                    elif key == "os":
                        version = lv_re.match(value).group(1)
                        if version:
                            description["comp"]["Linux kernel version"] = version
                        else:
                            logging.warning("Cannot properly extract Linux kernel version from {}".format(host_file))
                    elif key == "memory":
                        description["comp"]["mem size"] = value
                    elif key == "cpuModel":
                        description["comp"]["CPU model"] = value
                    elif key == "cores":
                        description["comp"]["number of CPU cores"] = value
        else:
            raise FileNotFoundError("There is no solution file {}".format(host_file))

        return identifier, description

    @staticmethod
    def __make_fake_benchexec(description, run, path):
        """
        Save a fake BenchExec report. If you need to add an additional information to the XML file then add it here.

        :param description: Description dictionary extracted from VerifierCloud TXT files.
        :param run: Run object prepared by this scheduler before run.
        :return: None
        """
        result = ET.Element("result", {
            "benchmarkname": "benchmark"
        })
        run = ET.SubElement(result, "run")
        ET.SubElement(run, "column", {
            'title': 'status',
            'value': str(description['status'])
        })
        ET.SubElement(run, "column", {
            'title': 'exitcode',
            'value': str(description['return value'])
        })

        with open(path, "w", encoding="utf8") as fp:
            fp.write(minidom.parseString(ET.tostring(result)).toprettyxml(indent="    "))

__author__ = 'Ilja Zakharov <ilja.zakharov@ispras.ru>'
