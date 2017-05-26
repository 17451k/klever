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
import json
from io import BytesIO

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.files import File as NewFile
from django.db.models import F
from django.utils.timezone import now
from django.utils.translation import ugettext_lazy as _

from bridge.vars import JOB_STATUS, PRIORITY, SCHEDULER_STATUS, SCHEDULER_TYPE, TASK_STATUS
from bridge.utils import file_checksum, logger, BridgeException

from jobs.models import RunHistory, JobFile, FileSystem, Job
from reports.models import ReportRoot, ReportUnknown, TaskStatistic, ReportComponent
from service.models import Scheduler, SolvingProgress, Task, Solution, VerificationTool, Node, NodesConfiguration,\
    SchedulerUser, Workload

from jobs.utils import JobAccess, change_job_status


class ServiceError(Exception):
    pass


class ScheduleTask:
    def __init__(self, job_id, description, archive):
        try:
            self.progress = SolvingProgress.objects\
                .annotate(job_status=F('job__status'), sch_status=F('scheduler__status'))\
                .get(job_id=job_id)
        except ObjectDoesNotExist:
            raise ServiceError('Solving progress of the job was not found')
        self.description = description
        try:
            priority = json.loads(self.description)['priority']
        except Exception:
            raise ServiceError('Wrong description format')
        if priority not in set(x[0] for x in PRIORITY):
            raise ServiceError('Wrong priority')
        if self.progress.job_status != JOB_STATUS[2][0]:
            raise ServiceError('The job is not processing')
        if self.progress.sch_status == SCHEDULER_STATUS[2][0]:
            raise ServiceError('The scheduler for tasks is disconnected')
        if compare_priority(self.progress.priority, priority):
            raise ServiceError('Priority of the task is too big')
        self.task_id = self.__create_task(archive)

    def __create_task(self, archive):
        task = Task.objects.create(
            progress=self.progress, archname=archive.name,
            archive=archive, description=self.description.encode('utf8')
        )
        SolvingProgress.objects.filter(id=self.progress.id)\
            .update(tasks_total=F('tasks_total') + 1, tasks_pending=F('tasks_pending') + 1)
        return task.id


class GetTaskStatus:
    def __init__(self, task_id):
        try:
            self.task = Task.objects.get(id=task_id)
        except ObjectDoesNotExist:
            raise ServiceError("The task '%s' was not found" % task_id)
        if Job.objects.get(solvingprogress=self.task.progress).status != JOB_STATUS[2][0]:
            raise ServiceError('The job is not processing')
        self.status = self.task.status


class GetSolution:
    def __init__(self, task_id):
        try:
            self.task = Task.objects.get(id=task_id)
        except ObjectDoesNotExist:
            raise ServiceError("The task '%s' was not found" % task_id)
        if Job.objects.get(solvingprogress=self.task.progress).status != JOB_STATUS[2][0]:
            raise ServiceError('The job is not processing')
        if self.task.status == TASK_STATUS[3][0]:
            if self.task.error is None:
                raise ServiceError("The task was finished with error but doesn't have its description")
        elif self.task.status == TASK_STATUS[2][0]:
            try:
                self.solution = Solution.objects.get(task=self.task)
            except ObjectDoesNotExist:
                raise ServiceError("The solution of the finished task doesn't exist")
        else:
            raise ServiceError('The task is not finished')


class RemoveTask:
    def __init__(self, task_id):
        try:
            self.task = Task.objects.get(id=task_id)
        except ObjectDoesNotExist:
            raise ServiceError("The task '%s' was not found" % task_id)
        if Job.objects.get(solvingprogress=self.task.progress).status != JOB_STATUS[2][0]:
            raise ServiceError('The job is not processing')
        if self.task.status == TASK_STATUS[3][0]:
            if self.task.error is None:
                raise ServiceError("The task was finished with error but doesn't have its description")
        elif self.task.status == TASK_STATUS[2][0]:
            try:
                Solution.objects.get(task=self.task)
            except ObjectDoesNotExist:
                raise ServiceError("The solution of the finished task doesn't exist")
        else:
            raise ServiceError('The task is not finished')
        self.task.delete()


class CancelTask:
    def __init__(self, task_id):
        try:
            self.task = Task.objects.get(id=task_id)
        except ObjectDoesNotExist:
            raise ServiceError("The task '%s' was not found" % task_id)
        if Job.objects.get(solvingprogress=self.task.progress).status != JOB_STATUS[2][0]:
            raise ServiceError('The job is not processing')

        progress = SolvingProgress.objects.get(id=self.task.progress_id)
        if self.task.status == TASK_STATUS[0][0]:
            if progress.tasks_pending > 0:
                progress.tasks_pending -= 1
        elif self.task.status == TASK_STATUS[1][0]:
            if progress.tasks_processing > 0:
                progress.tasks_processing -= 1
        else:
            raise ServiceError('The task status is wrong')
        progress.tasks_cancelled += 1
        progress.save()

        self.task.delete()


class FinishJobDecision:
    def __init__(self, inst, status, error=None):
        if isinstance(inst, SolvingProgress):
            self.progress = inst
            self.job = self.progress.job
        elif isinstance(inst, Job):
            self.job = inst
            try:
                self.progress = SolvingProgress.objects.get(job=self.job)
            except ObjectDoesNotExist:
                logger.exception('The job does not have solving progress')
                change_job_status(self.job, JOB_STATUS[5][0])
                return
        else:
            raise ValueError('Unsupported argument: %s' % type(inst))
        self.error = error
        self.status = self.__get_status(status)
        try:
            self.__remove_tasks()
        except ServiceError as e:
            logger.exception(e)
            self.progress.error = str(e)
            self.status = JOB_STATUS[5][0]
        if self.error is not None:
            if len(self.error) > 1024:
                logger.error("The job '%s' finished with large error: %s" % (self.job.identifier, self.error))
                self.error = "Length of error for job '%s' is large (1024 characters is maximum)" % self.job.identifier
                self.status = JOB_STATUS[7][0]
            self.progress.error = self.error
        self.progress.finish_date = now()
        self.progress.save()
        change_job_status(self.job, self.status)

    def __remove_tasks(self):
        if self.progress.job.status == JOB_STATUS[1][0]:
            return
        elif self.progress.job.status != JOB_STATUS[2][0]:
            raise ServiceError('The job is not processing')
        elif self.progress.task_set.filter(status__in={TASK_STATUS[0][0], TASK_STATUS[0][1]}).count() > 0:
            raise ServiceError('There are unfinished tasks')
        elif self.progress.task_set.filter(status=TASK_STATUS[3][0], error=None).count() > 0:
            raise ServiceError('There are tasks finished with error and without error descriptions')
        elif self.progress.task_set.filter(status=TASK_STATUS[2][0], solution=None).count() > 0:
            raise ServiceError('There are finished tasks without solutions')
        self.progress.task_set.all().delete()

    def __get_status(self, status):
        if status not in set(x[0] for x in JOB_STATUS):
            raise ValueError('Unsupported status: %s' % status)
        if status == JOB_STATUS[3][0]:
            if ReportComponent.objects.filter(root=self.progress.job.reportroot, finish_date=None).count() > 0:
                self.error = 'There are unfinished reports'
                return JOB_STATUS[5][0]
            try:
                core_r = ReportComponent.objects.get(parent=None, root=self.progress.job.reportroot)
            except ObjectDoesNotExist:
                self.error = "The job doesn't have Core report"
                return JOB_STATUS[5][0]
            if ReportUnknown.objects\
                    .filter(parent=core_r, component=core_r.component, root=self.progress.job.reportroot).count() > 0:
                status = JOB_STATUS[4][0]
        elif status == JOB_STATUS[4][0]:
            try:
                core_r = ReportComponent.objects.get(parent=None, root=self.progress.job.reportroot)
            except ObjectDoesNotExist:
                pass
            else:
                if ReportComponent.objects.filter(root=self.progress.job.reportroot, finish_date=None).count() > 0 \
                        or ReportUnknown.objects.filter(parent=core_r, component=core_r.component,
                                                        root=self.progress.job.reportroot).count() == 0:
                    status = JOB_STATUS[7][0]
            if self.error is None:
                self.error = "The scheduler hasn't given an error description"
        return status


class KleverCoreStartDecision:
    def __init__(self, job):
        try:
            progress = SolvingProgress.objects.get(job=job)
        except ObjectDoesNotExist:
            raise ValueError('job decision was not successfully started')
        if progress.start_date is not None:
            raise ValueError('the "start" report of Core was already uploaded')
        elif progress.finish_date is not None:
            raise ValueError('the job is not solving already')
        progress.start_date = now()
        progress.save()


class StopDecision:
    def __init__(self, job):
        if job.status not in [JOB_STATUS[1][0], JOB_STATUS[2][0]]:
            raise BridgeException(_("Only pending and processing jobs can be stopped"))
        try:
            self.progress = SolvingProgress.objects.get(job=job)
        except ObjectDoesNotExist:
            raise BridgeException(_('The job solving progress does not exist'))

        change_job_status(job, JOB_STATUS[6][0])
        self.__clear_tasks()

    def __clear_tasks(self):
        pending_num = self.progress.task_set.filter(status=TASK_STATUS[0][0]).count()
        processing_num = self.progress.task_set.filter(status=TASK_STATUS[1][0]).count()
        self.progress.tasks_processing = self.progress.tasks_pending = 0
        self.progress.tasks_cancelled += processing_num + pending_num
        self.progress.finish_date = now()
        self.progress.error = "The job was cancelled"
        self.progress.save()
        # If there are a lot of tasks that are not still deleted it could be too long
        # as there is request to DB for each task here (pre_delete signal)
        self.progress.task_set.all().delete()


class GetTasks:
    def __init__(self, sch_type, tasks):
        try:
            self._scheduler = Scheduler.objects.get(type=sch_type)
        except ObjectDoesNotExist:
            raise ServiceError('The scheduler was not found')
        self._operators = {}
        self._progresses = {}
        self._tasks_statuses = {}
        self._solution_req = set()
        self._data = {
            'jobs': {'pending': [], 'processing': [], 'error': [], 'finished': [], 'cancelled': []},
            'tasks': {'pending': [], 'processing': [], 'error': [], 'finished': []},
            'task errors': {},
            'task descriptions': {},
            'task solutions': {},
            'job errors': {},
            'job configurations': {}
        }
        self.__get_tasks(tasks)
        try:
            self.newtasks = json.dumps(self._data, ensure_ascii=False, sort_keys=True, indent=4)
        except ValueError:
            raise ServiceError("Can't dump json")

    def __get_tasks(self, tasks):
        data = json.loads(tasks)
        if 'jobs' not in data:
            data['jobs'] = {'error': [], 'finished': []}
        if 'tasks' not in data:
            data['tasks'] = {'pending': [], 'processing': [], 'error': [], 'finished': []}
        for x in ['error', 'finished']:
            if x not in data['jobs']:
                data['jobs'][x] = []
        for x in ['pending', 'processing', 'error', 'finished']:
            if x not in data['tasks']:
                data['tasks'][x] = []
        if 'task errors' not in data:
            data['task errors'] = {}
        if 'job errors' not in data:
            data['job errors'] = {}

        # Finish job decisions and add pending/processing/cancelled jobs
        if self._scheduler.type == SCHEDULER_TYPE[0][0]:
            for progress in SolvingProgress.objects.filter(job__status=JOB_STATUS[1][0]).select_related('job'):
                if progress.job.identifier in data['jobs']['finished']:
                    FinishJobDecision(progress, JOB_STATUS[5][0], "The job can't be finished as it is still pending")
                elif progress.job.identifier in data['jobs']['error']:
                    FinishJobDecision(progress, JOB_STATUS[4][0], data['job errors'].get(progress.job.identifier))
                else:
                    self._data['job configurations'][progress.job.identifier] = \
                        json.loads(progress.configuration.decode('utf8'))
                    self._data['job configurations'][progress.job.identifier]['task resource limits'] = \
                        self.__get_tasks_limits(progress.job_id)
                    self._data['jobs']['pending'].append(progress.job.identifier)
            for progress in SolvingProgress.objects.filter(job__status=JOB_STATUS[2][0]).select_related('job'):
                if progress.job.identifier in data['jobs']['finished']:
                    FinishJobDecision(progress, JOB_STATUS[3][0])
                elif progress.job.identifier in data['jobs']['error']:
                    FinishJobDecision(progress, JOB_STATUS[4][0], data['job errors'].get(progress.job.identifier))
                else:
                    self._data['jobs']['processing'].append(progress.job.identifier)
            for progress in SolvingProgress.objects.filter(job__status=JOB_STATUS[6][0]).values_list('job__identifier'):
                self._data['jobs']['cancelled'].append(progress[0])

        # Everything with tasks
        all_tasks = dict((x[0].lower(), []) for x in TASK_STATUS)
        for task in Task.objects.filter(progress__scheduler=self._scheduler, progress__job__status=JOB_STATUS[2][0])\
                .annotate(sol=F('solution__id')).order_by('id'):
            all_tasks[task.status.lower()].append(task)

        for old_status in ['error', 'finished']:
            for task in all_tasks[old_status]:
                for new_status in ['pending', 'processing', 'error', 'finished']:
                    if str(task.pk) in data['tasks'][new_status]:
                        raise ServiceError("The task '%s' with status '%s' has become '%s'" % (
                            task.id, old_status.upper(), new_status.upper()
                        ))
        for task in all_tasks['processing']:
            if str(task.id) in data['tasks']['pending']:
                raise ServiceError("The task '%s' with status 'PROCESSING' has become 'PENDING'" % task.id)

        for task in all_tasks['pending']:
            if str(task.id) in data['tasks']['pending']:
                self._data['tasks']['pending'].append(str(task.id))
                self._solution_req.add(task.id)
                self.__add_description(task)
            elif str(task.id) in data['tasks']['processing']:
                self.__change_status(task, 'pending', 'processing')
                self._data['tasks']['processing'].append(str(task.id))
                self._solution_req.add(task.id)
                self.__add_description(task)
            elif str(task.id) in data['tasks']['finished']:
                self.__change_status(task, 'pending', 'finished')
                if task.sol is None:
                    # TODO: email notification
                    logger.error('There are finished tasks without solutions', stack_info=True)
            elif str(task.id) in data['tasks']['error']:
                if str(task.id) in data['task errors']:
                    if len(data['task errors'][str(task.id)]) > 1024:
                        task.error = "Length of error for task with id '%s' must be less than 1024 characters" % task.id
                    else:
                        task.error = data['task errors'][str(task.id)]
                else:
                    task.error = "The scheduler hasn't given error description"
                task.save()
                self.__change_status(task, 'pending', 'error')
            else:
                self._data['tasks']['pending'].append(str(task.id))
                self._solution_req.add(task.id)
                self.__add_description(task)
        for task in all_tasks['processing']:
            if str(task.id) in data['tasks']['processing']:
                self._data['tasks']['processing'].append(str(task.id))
                self._solution_req.add(task.id)
            elif str(task.id) in data['tasks']['finished']:
                self.__change_status(task, 'processing', 'finished')
                if task.sol is None:
                    # TODO: email notification
                    logger.error('There are finished tasks without solutions', stack_info=True)
            elif str(task.id) in data['tasks']['error']:
                if str(task.id) in data['task errors']:
                    if len(data['task errors'][str(task.id)]) > 1024:
                        task.error = "Length of error for task with id '%s' must be less than 1024 characters" % task.id
                    else:
                        task.error = data['task errors'][str(task.id)]
                else:
                    task.error = "The scheduler hasn't given error description"
                task.save()
                self.__change_status(task, 'processing', 'error')
            else:
                self._data['tasks']['processing'].append(str(task.id))
                self._solution_req.add(task.id)
        # There are no cancelled tasks because when the task is cancelled it is deleted,
        # and there are no changes of status to cancelled in get_jobs_and_tasks_status()
        self.__finish_with_tasks()

    def __add_description(self, task):
        task_id = str(task.id)
        self._data['task descriptions'][task_id] = {'description': json.loads(task.description.decode('utf8'))}
        if self._scheduler.type == SCHEDULER_TYPE[1][0]:
            if task.progress_id in self._operators:
                self._data['task descriptions'][task_id]['VerifierCloud user name'] = \
                    self._operators[task.progress_id][0]
                self._data['task descriptions'][task_id]['VerifierCloud user password'] = \
                    self._operators[task.progress_id][1]
            else:
                try:
                    root = ReportRoot.objects.get(job__solvingprogress=task.progress)
                    sch_user = SchedulerUser.objects.get(user=root.user)
                except ObjectDoesNotExist:
                    return
                else:
                    self._operators[task.progress_id] = (sch_user.login, sch_user.password)
                    self._data['task descriptions'][task_id]['VerifierCloud user name'] = sch_user.login
                    self._data['task descriptions'][task_id]['VerifierCloud user password'] = sch_user.password

    def __change_status(self, task, old, new):
        old = old.upper()
        new = new.upper()
        fields = {
            TASK_STATUS[0][0]: 'tasks_pending',
            TASK_STATUS[1][0]: 'tasks_processing',
            TASK_STATUS[2][0]: 'tasks_finished',
            TASK_STATUS[3][0]: 'tasks_error',
            TASK_STATUS[4][0]: 'tasks_cancelled'
        }
        if task.progress_id not in self._progresses:
            self._progresses[task.progress_id] = SolvingProgress.objects.get(id=task.progress_id)
        old_num = getattr(self._progresses[task.progress_id], fields[old])
        if old_num <= 0:
            logger.error('Something wrong with SolvingProgress cache: '
                         'number of %s tasks is 0, but there is at least one such task in the system' % old)
        else:
            setattr(self._progresses[task.progress_id], fields[old], old_num - 1)
        new_num = getattr(self._progresses[task.progress_id], fields[new])
        setattr(self._progresses[task.progress_id], fields[new], new_num + 1)

        if new not in self._tasks_statuses:
            self._tasks_statuses[new] = set()
        self._tasks_statuses[new].add(task.id)

    def __finish_with_tasks(self):
        for status in self._tasks_statuses:
            Task.objects.filter(id__in=self._tasks_statuses[status]).update(status=status)
        for progress_id in self._progresses:
            self._progresses[progress_id].save()
        for solution in Solution.objects.filter(task_id__in=self._solution_req):
            self._data['task solutions'][str(solution.task_id)] = json.loads(solution.description.decode('utf8'))

    def __get_tasks_limits(self, job_id):
        self.__is_not_used()
        try:
            tasks = FileSystem.objects.get(
                job__job_id=job_id, job__version=F('job__job__version'), name='tasks.json', parent=None
            )
        except ObjectDoesNotExist:
            logger.error("The tasks.json file doesn't exists")
            return {}
        try:
            with open(os.path.join(settings.MEDIA_ROOT, tasks.file.file.name), mode='r', encoding='utf8') as fp:
                return json.load(fp)
        except Exception as e:
            logger.exception(e)
            return {}

    def __is_not_used(self):
        pass


class GetTaskData:
    def __init__(self, task_id):
        try:
            self.task = Task.objects.get(id=task_id)
        except ObjectDoesNotExist:
            raise ServiceError('The task %s was not found' % task_id)
        if Job.objects.get(solvingprogress=self.task.progress).status != JOB_STATUS[2][0]:
            raise ServiceError('The job is not processing')
        if self.task.status not in {TASK_STATUS[0][0], TASK_STATUS[1][0]}:
            raise ServiceError('The task status is wrong')


class SaveSolution:
    def __init__(self, task_id, archive, description):
        try:
            self.task = Task.objects.get(id=task_id)
        except ObjectDoesNotExist:
            raise ServiceError('The task %s was not found' % task_id)
        if not Job.objects.filter(solvingprogress=self.task.progress_id, status=JOB_STATUS[2][0]).exists():
            raise ServiceError('The job is not processing')
        self.__create_solution(description, archive)

    def __create_solution(self, description, archive):
        try:
            Solution.objects.get(task=self.task)
            raise ServiceError('The task already has solution')
        except ObjectDoesNotExist:
            pass
        Solution.objects.create(task=self.task, description=description.encode('utf8'),
                                archive=archive, archname=archive.name)
        progress = SolvingProgress.objects.get(id=self.task.progress_id)
        progress.solutions += 1
        progress.save()
        solved_tasks = progress.tasks_finished + progress.tasks_error
        try:
            wall_time = json.loads(description)['resources']['wall time']
        except Exception as e:
            raise ServiceError('Expected another format of solution description: %s' % e)
        TaskStatistic.objects.all().update(
            average_time=(F('average_time') * F('number_of_tasks') + wall_time)/(F('number_of_tasks') + 1),
            number_of_tasks=F('number_of_tasks') + 1
        )
        ReportRoot.objects.filter(job__solvingprogress=self.task.progress_id) \
            .update(average_time=(F('average_time') * solved_tasks + wall_time) / (solved_tasks + 1))


class SetNodes:
    def __init__(self, node_data):
        try:
            self.__read_node_data(node_data)
        except IndexError or KeyError:
            NodesConfiguration.objects.all().delete()
            raise ServiceError('Wrong nodes data format')
        except Exception:
            NodesConfiguration.objects.all().delete()
            raise ServiceError('Unknown error')

    def __read_node_data(self, nodes_data):
        NodesConfiguration.objects.all().delete()
        for config in json.loads(nodes_data):
            nodes_conf = NodesConfiguration.objects.create(
                cpu=config['CPU model'], cores=config['CPU number'],
                ram=config['RAM memory'], memory=config['disk memory']
            )
            for hostname in config['nodes']:
                self.__create_node(nodes_conf, hostname, config['nodes'][hostname])

    def __create_node(self, conf, hostname, data):
        self.__is_not_used()
        workload = None
        if 'workload' in data:
            workload = Workload.objects.create(
                cores=data['workload']['reserved CPU number'],
                ram=data['workload']['reserved RAM memory'],
                memory=data['workload']['reserved disk memory'],
                jobs=data['workload']['running verification jobs'],
                tasks=data['workload']['running verification tasks'],
                for_jobs=data['workload']['available for jobs'],
                for_tasks=data['workload']['available for tasks']
            )
        Node.objects.create(config=conf, hostname=hostname, status=data['status'], workload=workload)

    def __is_not_used(self):
        pass


class UpdateTools:
    def __init__(self, sch_type, tools_data):
        try:
            self.scheduler = Scheduler.objects.get(type=sch_type)
        except ObjectDoesNotExist:
            raise ServiceError('Scheduler was not found')
        try:
            self.__read_tools_data(tools_data)
        except ValueError or KeyError:
            raise ServiceError('Wrong tools data format')
        except Exception:
            raise ServiceError('Unknown error')

    def __read_tools_data(self, data):
        VerificationTool.objects.filter(scheduler=self.scheduler).delete()
        VerificationTool.objects.bulk_create(list(
            VerificationTool(scheduler=self.scheduler, name=tool['tool'], version=tool['version'])
            for tool in json.loads(data)
        ))


class SetSchedulersStatus:
    def __init__(self, statuses):
        try:
            self.statuses = json.loads(statuses)
        except ValueError:
            raise ServiceError('Incorrect format of statuses')
        self.__update_statuses()

    def __update_statuses(self):
        sch_type_map = {}
        for sch_type in SCHEDULER_TYPE:
            sch_type_map[sch_type[1]] = sch_type[0]
        for sch_type in self.statuses:
            try:
                scheduler = Scheduler.objects.get(type=sch_type_map[sch_type])
            except ObjectDoesNotExist:
                raise ServiceError('Scheduler was not found')
            if self.statuses[sch_type] not in list(x[0] for x in SCHEDULER_STATUS):
                raise ServiceError('Scheduler status is wrong')
            if scheduler.status == self.statuses[sch_type]:
                continue
            if self.statuses[sch_type] == SCHEDULER_STATUS[2][0]:
                self.__finish_tasks(scheduler)
            scheduler.status = self.statuses[sch_type]
            scheduler.save()

    def __finish_tasks(self, scheduler):
        self.__is_not_used()
        for progress in scheduler.solvingprogress_set.filter(job__status=JOB_STATUS[2][0], finish_date=None):
            pending_num = Task.objects.filter(status=TASK_STATUS[0][0], progress=progress)\
                .update(error='Task was finished with error due to scheduler is disconnected')
            processing_num = Task.objects.filter(status=TASK_STATUS[1][0], progress=progress)\
                .update(error='Task was finished with error due to scheduler is disconnected')
            progress.tasks_pending = progress.tasks_processing = 0
            progress.tasks_error += pending_num + processing_num
            if scheduler.type == SCHEDULER_TYPE[0][0]:
                progress.finish_date = now()
                progress.error = 'Klever scheduler was disconnected'
                change_job_status(progress.job, JOB_STATUS[7][0])
            progress.save()

    def __is_not_used(self):
        pass


def compare_priority(priority1, priority2):
    cnt = 0
    for pr in PRIORITY:
        cnt += 1
        if pr[0] == priority1:
            priority1 = cnt
        if pr[0] == priority2:
            priority2 = cnt
    if not isinstance(priority1, int):
        priority1 = 0
    if not isinstance(priority2, int):
        priority2 = 0
    return priority1 > priority2


class NodesData(object):
    def __init__(self):
        self.conf_data = []
        self.total_data = {
            'cores': {0: 0, 1: 0},
            'ram': {0: 0, 1: 0},
            'memory': {0: 0, 1: 0},
            'jobs': 0,
            'tasks': 0
        }
        self.nodes = []
        self.__get_data()

    def __get_data(self):
        cnt = 0
        for conf in NodesConfiguration.objects.all():
            cnt += 1
            conf_data = {
                'id': conf.pk,
                'conf': {
                    'ram': int(conf.ram / 10**9),
                    'cores': conf.cores,
                    'memory': int(conf.memory / 10**9),
                    'num_of_nodes': conf.node_set.count()
                },
                'cnt': cnt,
                'cpu': conf.cpu,
                'cores': {0: 0, 1: 0},
                'ram': {0: 0, 1: 0},
                'memory': {0: 0, 1: 0},
                'jobs': 0,
                'tasks': 0
            }
            for node in conf.node_set.all():
                node_data = {
                    'conf_id': conf.pk,
                    'hostname': node.hostname,
                    'status': node.get_status_display(),
                    'cpu': conf.cpu,
                    'cores': '-',
                    'ram': '-',
                    'memory': '-',
                    'tasks': '-',
                    'jobs': '-',
                    'for_tasks': '-',
                    'for_jobs': '-'
                }
                if node.workload is not None:
                    conf_data['cores'][0] += node.workload.cores
                    conf_data['cores'][1] += conf.cores
                    conf_data['ram'][0] += node.workload.ram
                    conf_data['ram'][1] += conf.ram
                    conf_data['memory'][0] += node.workload.memory
                    conf_data['memory'][1] += conf.memory
                    node_data.update({
                        'cores': "%s/%s" % (node.workload.cores, conf.cores),
                        'ram': "%s/%s" % (int(node.workload.ram / 10**9),
                                          int(conf.ram / 10**9)),
                        'memory': "%s/%s" % (int(node.workload.memory / 10**9),
                                             int(conf.memory / 10**9)),
                        'tasks': node.workload.tasks,
                        'jobs': node.workload.jobs,
                        'for_jobs': node.workload.for_jobs,
                        'for_tasks': node.workload.for_tasks,
                    })
                self.nodes.append(node_data)
            self.total_data['cores'] = (self.total_data['cores'][0] + conf_data['cores'][0],
                                        self.total_data['cores'][1] + conf_data['cores'][1])
            self.total_data['ram'] = (self.total_data['ram'][0] + conf_data['ram'][0],
                                      self.total_data['ram'][1] + conf_data['ram'][1])
            self.total_data['memory'] = (self.total_data['memory'][0] + conf_data['memory'][0],
                                         self.total_data['memory'][1] + conf_data['memory'][1])
            conf_data['cores'] = "%s/%s" % (conf_data['cores'][0], conf_data['cores'][1])
            conf_data['ram'] = "%s/%s" % (int(conf_data['ram'][0] / 10**9),
                                          int(conf_data['ram'][1] / 10**9))
            conf_data['memory'] = "%s/%s" % (int(conf_data['memory'][0] / 10**9),
                                             int(conf_data['memory'][1] / 10**9))
            self.conf_data.append(conf_data)
        self.total_data['cores'] = "%s/%s" % (self.total_data['cores'][0], self.total_data['cores'][1])
        self.total_data['ram'] = "%s/%s" % (int(self.total_data['ram'][0] / 10**9),
                                            int(self.total_data['ram'][1] / 10**9))
        self.total_data['memory'] = "%s/%s" % (int(self.total_data['memory'][0] / 10**9),
                                               int(self.total_data['memory'][1] / 10**9))


class StartJobDecision:
    def __init__(self, user, job_id, data):
        self.operator = user
        self.data = data
        self.job = self.__get_job(job_id)
        self.job_scheduler = self.__get_scheduler()
        self.klever_core_data = self.__get_klever_core_data()
        self.__check_schedulers()
        self.progress = self.__create_solving_progress()
        try:
            ReportRoot.objects.get(job=self.job).delete()
        except ObjectDoesNotExist:
            pass
        ReportRoot.objects.create(user=self.operator, job=self.job)
        self.job.status = JOB_STATUS[1][0]
        self.job.weight = self.data[4][6]
        self.job.save()

    def __get_klever_core_data(self):
        scheduler = SCHEDULER_TYPE[0][1]
        for sch in SCHEDULER_TYPE:
            if sch[0] == self.data[0][1]:
                scheduler = sch[1]
                break
        return {
            'identifier': self.job.identifier,
            'priority': self.data[0][0],
            'abstract task generation priority': self.data[0][2],
            'task scheduler': scheduler,
            'resource limits': {
                'memory size': int(self.data[2][0] * 10**9),
                'number of CPU cores': self.data[2][1],
                'disk memory size': int(self.data[2][2] * 10**9),
                'CPU model': self.data[2][3] if isinstance(self.data[2][3], str) and len(self.data[2][3]) > 0 else None,
                'CPU time': int(self.data[2][4] * 10**4 * 6) if self.data[2][4] is not None else None,
                'wall time': int(self.data[2][5] * 10**4 * 6) if self.data[2][5] is not None else None
            },
            'keep intermediate files': self.data[4][0],
            'upload input files of static verifiers': self.data[4][1],
            'upload other intermediate files': self.data[4][2],
            'allow local source directories use': self.data[4][3],
            'ignore other instances': self.data[4][4],
            'ignore failed sub-jobs': self.data[4][5],
            'weight': self.data[4][6],
            'logging': {
                'formatters': [
                    {
                        'name': 'brief',
                        'value': self.data[3][1]
                    },
                    {
                        'name': 'detailed',
                        'value': self.data[3][3]
                    }
                ],
                'loggers': [
                    {
                        'name': 'default',
                        'handlers': [
                            {
                                'formatter': 'brief',
                                'level': self.data[3][0],
                                'name': 'console'
                            },
                            {
                                'formatter': 'detailed',
                                'level': self.data[3][2],
                                'name': 'file'
                            }
                        ]
                    }
                ]
            },
            'parallelism': {
                'Sub-jobs processing': self.data[1][0],
                'Build': self.data[1][1],
                'Tasks generation': self.data[1][2]
            }
        }

    def __get_scheduler(self):
        try:
            return Scheduler.objects.get(type=self.data[0][1])
        except ObjectDoesNotExist:
            raise BridgeException(_('The scheduler was not found'))

    def __get_job(self, job_id):
        try:
            job = Job.objects.get(pk=job_id)
        except ObjectDoesNotExist:
            raise BridgeException(_('The job was not found'))
        if not JobAccess(self.operator, job).can_decide():
            raise BridgeException(_("You don't have an access to start decision of this job"))
        return job

    def __create_solving_progress(self):
        try:
            self.job.solvingprogress.delete()
        except ObjectDoesNotExist:
            pass
        self.__save_configuration()
        return SolvingProgress.objects.create(
            job=self.job, priority=self.data[0][0],
            scheduler=self.job_scheduler,
            configuration=json.dumps(self.klever_core_data, ensure_ascii=False, sort_keys=True, indent=4).encode('utf8')
        )

    def __save_configuration(self):
        m = BytesIO(json.dumps(self.klever_core_data, ensure_ascii=False, sort_keys=True, indent=4).encode('utf8'))
        check_sum = file_checksum(m)
        try:
            db_file = JobFile.objects.get(hash_sum=check_sum)
        except ObjectDoesNotExist:
            db_file = JobFile()
            db_file.file.save('job-%s.conf' % self.job.identifier[:5], NewFile(m))
            db_file.hash_sum = check_sum
            db_file.save()
        RunHistory.objects.create(job=self.job, operator=self.operator, configuration=db_file)

    def __check_schedulers(self):
        try:
            klever_sch = Scheduler.objects.get(type=SCHEDULER_TYPE[0][0])
        except ObjectDoesNotExist:
            raise BridgeException()
        if klever_sch.status == SCHEDULER_STATUS[2][0]:
            raise BridgeException(_('The Klever scheduler is disconnected'))
        if self.job_scheduler.type == SCHEDULER_TYPE[1][0]:
            if self.job_scheduler.status == SCHEDULER_STATUS[2][0]:
                raise BridgeException(_('The VerifierCloud scheduler is disconnected'))
            try:
                self.operator.scheduleruser
            except ObjectDoesNotExist:
                raise BridgeException(_("You didn't specify credentials for VerifierCloud"))
