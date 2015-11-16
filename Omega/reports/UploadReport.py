import json
import pytz
import hashlib
from io import BytesIO
from datetime import datetime
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
from django.db.models import Q
from django.core.files import File as Newfile
from Omega.vars import JOB_STATUS
from reports.models import *
from reports.utils import save_attrs
from marks.utils import ConnectReportWithMarks
from service.utils import PSIFinishDecision, PSIStartDecision


class UploadReport(object):

    def __init__(self, job, data):
        self.job = job
        self.data = {}
        self.ordered_attrs = []
        self.error = self.__check_data(data)
        if self.error is not None:
            self.__job_failed(self.error)
            return
        self.parent = None
        self.error = self.__get_parent()
        if self.error is not None:
            self.__job_failed(self.error)
            return
        self.root = None
        self.__get_root_report()
        if self.error is not None:
            self.__job_failed(self.error)
            return
        self.error = self.__upload()
        if self.error is not None:
            self.__job_failed(self.error)

    def __job_failed(self, error=None):
        PSIFinishDecision(self.job, error)

    def __check_data(self, data):
        if not isinstance(data, dict):
            return 'Data is not a dictionary'
        if 'type' not in data or 'id' not in data or len(data['id']) == 0:
            return 'Type and id are required'

        if 'resources' in data:
            if not isinstance(data['resources'], dict) and all(
                    x in data['resources'] for x in [
                        'wall time', 'CPU time', 'max mem size']):
                return 'Resources has wrong format: %s' % json.dumps(
                    data['resources'])

        self.data = {'type': data['type'], 'id': data['id']}
        if 'desc' in data:
            self.data['description'] = data['desc']
        if 'comp' in data:
            err = self.__check_comp(data['comp'])
            if err is not None:
                return err
        if 'attrs' in data:
            err = self.__check_attrs(data['attrs'])
            if err is not None:
                return err
        if 'name' in data and len(data['name']) > 15:
            return 'Component name is too long (max 15 symbols expected)'

        if data['type'] == 'start':
            if data['id'] == '/':
                result = PSIStartDecision(self.job)
                if result.error is not None:
                    return result.error
                try:
                    self.data.update({
                        'attrs': data['attrs'],
                        'comp': data['comp'],
                    })
                except KeyError as e:
                    return "Property '%s' is required." % e
            else:
                try:
                    self.data.update({
                        'parent id': data['parent id'],
                        'name': data['name']
                    })
                except KeyError as e:
                    return "Property '%s' is required." % e
                if 'attrs' in data:
                    self.data['attrs'] = data['attrs']
                if 'comp' in data:
                    self.data['comp'] = data['comp']
        elif data['type'] == 'finish':
            try:
                self.data.update({
                    'log': data['log'],
                    'data': data['data'],
                    'resources': data['resources'],
                })
            except KeyError as e:
                return "Property '%s' is required." % e
        elif data['type'] == 'attrs':
            try:
                self.data['attrs'] = data['attrs']
            except KeyError as e:
                return "Property '%s' is required." % e
        elif data['type'] == 'verification':
            try:
                self.data.update({
                    'parent id': data['parent id'],
                    'attrs': data['attrs'],
                    'name': data['name'],
                    'resources': data['resources'],
                    'log': data['log'],
                    'data': data['data'],
                })
            except KeyError as e:
                return "Property '%s' is required." % e
            if 'comp' in data:
                self.data['comp'] = data['comp']
        elif data['type'] == 'safe':
            try:
                self.data.update({
                    'parent id': data['parent id'],
                    'proof': data['proof'],
                    'attrs': data['attrs'],
                })
            except KeyError as e:
                return "Property '%s' is required." % e
        elif data['type'] == 'unknown':
            try:
                self.data.update({
                    'parent id': data['parent id'],
                    'problem desc': data['problem desc']
                })
            except KeyError as e:
                return "Property '%s' is required." % e
            if 'attrs' in data:
                self.data['attrs'] = data['attrs']
        elif data['type'] == 'unsafe':
            try:
                self.data.update({
                    'parent id': data['parent id'],
                    'error trace': data['error trace'],
                    'attrs': data['attrs'],
                })
            except KeyError as e:
                return "Property '%s' is required." % e
        else:
            return "Report type is not supported"
        return None

    def __check_comp(self, descr):
        self.ccc = 0
        if not isinstance(descr, list):
            return 'Wrong computer description format'
        for d in descr:
            if not isinstance(d, dict):
                return 'Wrong computer description format'
            if len(d) != 1:
                return 'Wrong computer description format'
            if not isinstance(d[next(iter(d))], str) and not isinstance(d[next(iter(d))], int):
                return 'Wrong computer description format'
        return None

    def __check_attrs(self, attrs):
        self.ccc = 0
        if not isinstance(attrs, list):
            return 'Wrong attributes format'
        for a in attrs:
            if not isinstance(a, dict):
                return 'Wrong attributes format'
        return None

    def __get_root_report(self):
        try:
            self.root = self.job.reportroot
        except ObjectDoesNotExist:
            self.error = "Can't find report root"
            return

    def __get_parent(self):
        if 'parent id' in self.data:
            if self.data['parent id'] == '/':
                try:
                    self.parent = ReportComponent.objects.get(
                        root=self.job.reportroot,
                        identifier=self.job.identifier
                    )
                except ObjectDoesNotExist:
                    return 'Parent was not found'
            else:
                try:
                    self.parent = ReportComponent.objects.get(
                        root=self.job.reportroot,
                        identifier__endswith=('##' + self.data['parent id'])
                    )
                except ObjectDoesNotExist:
                    return 'Parent was not found'
                except MultipleObjectsReturned:
                    return 'Identifiers are not unique'
        elif self.data['id'] == '/':
            return None
        else:
            try:
                curr_report = ReportComponent.objects.get(
                    identifier__startswith=self.job.identifier,
                    identifier__endswith=("##%s" % self.data['id']))
                self.parent = ReportComponent.objects.get(
                    root=self.job.reportroot, pk=curr_report.parent_id)
            except ObjectDoesNotExist:
                return None
        return None

    def __upload(self):
        actions = {
            'start': self.__create_report_component,
            'finish': self.__finish_report_component,
            'attrs': self.__update_attrs,
            'verification': self.__create_report_component,
            'unsafe': self.__create_report_unsafe,
            'safe': self.__create_report_safe,
            'unknown': self.__create_report_unknown
        }
        identifier = self.data['id']
        if identifier == '/':
            identifier = self.job.identifier
        elif self.parent is not None:
            identifier = "%s##%s" % (self.parent.identifier, identifier)
        else:
            identifier = "##%s" % identifier
        report = actions[self.data['type']](identifier)
        if report is None:
            return 'Error while saving report'
        single_attrs_order = []
        for attr in list(reversed(self.ordered_attrs)):
            if attr not in single_attrs_order:
                single_attrs_order.insert(0, attr)
            elif self.data['type'] not in ['safe', 'unsafe', 'unknown']:
                self.__job_failed("Got double attribute: '%s' for report"
                                  " with type '%s' and id '%s'" %
                                  (attr, self.data['type'], self.data['id']))
        for attr_name in single_attrs_order:
            ReportAttrOrder.objects.get_or_create(
                name=AttrName.objects.get_or_create(name=attr_name)[0],
                report_id=report.pk
            )
        return None

    def __create_report_component(self, identifier):
        try:
            return ReportComponent.objects.get(identifier=identifier)
        except ObjectDoesNotExist:
            report = ReportComponent(identifier=identifier)

        report.parent = self.parent
        report.root = self.root

        component_name = 'Psi'
        if 'name' in self.data:
            component_name = self.data['name']
        component, tmp = Component.objects.get_or_create(name=component_name)
        report.component = component

        if 'comp' in self.data:
            computer_desc = json.dumps(self.data['comp'])
            try:
                computer = Computer.objects.get(description=computer_desc)
            except ObjectDoesNotExist:
                computer = Computer()
                computer.description = computer_desc
                computer.save()
            report.computer = computer
        else:
            report.computer = self.parent.computer

        if 'resources' in self.data:
            resources = Resource()
            resources.cpu_time = int(self.data['resources']['CPU time'])
            resources.memory = int(self.data['resources']['max mem size'])
            resources.wall_time = int(self.data['resources']['wall time'])
            resources.save()
            report.resource = resources
        if 'log' in self.data:
            file_content = BytesIO(self.data['log'].encode('utf8'))
            check_sum = hashlib.md5(file_content.read()).hexdigest()
            try:
                file_in_db = File.objects.get(hash_sum=check_sum)
            except ObjectDoesNotExist:
                file_in_db = File()
                file_in_db.file.save(component_name + '.log',
                                     Newfile(file_content))
                file_in_db.hash_sum = check_sum
                file_in_db.save()
            report.log = file_in_db
        if 'data' in self.data:
            report.data = self.data['data'].encode('utf8')
        if 'description' in self.data:
            report.description = self.data['description'].encode('utf8')
        report.start_date = pytz.timezone('UTC').localize(datetime.now())

        if self.data['type'] == 'verification':
            report.finish_date = report.start_date
        report.save()

        self.__add_attrs(report)

        if 'resources' in self.data:
            self.__update_parent_resources(report)

        return report

    def __update_attrs(self, identifier):
        try:
            report = ReportComponent.objects.get(
                identifier__startswith=self.job.identifier,
                identifier__endswith=identifier)
        except ObjectDoesNotExist:
            return None
        report.save()

        self.__add_attrs(report)
        return report

    def __finish_report_component(self, identifier):
        try:
            report = ReportComponent.objects.get(
                identifier__startswith=self.job.identifier,
                identifier__endswith=identifier)
        except ObjectDoesNotExist:
            return None

        if 'resources' in self.data:
            resources = Resource()
            resources.cpu_time = int(self.data['resources']['CPU time'])
            resources.memory = int(self.data['resources']['max mem size'])
            resources.wall_time = int(self.data['resources']['wall time'])
            resources.save()
            report.resource = resources
        if 'log' in self.data:
            file_content = BytesIO(self.data['log'].encode('utf8'))
            check_sum = hashlib.md5(file_content.read()).hexdigest()
            try:
                file_in_db = File.objects.get(hash_sum=check_sum)
            except ObjectDoesNotExist:
                file_in_db = File()
                file_in_db.file.save(report.component.name + '.log',
                                     Newfile(file_content))
                file_in_db.hash_sum = check_sum
                file_in_db.save()
            report.log = file_in_db
        if 'data' in self.data:
            report.data = self.data['data'].encode('utf8')
        if 'description' in self.data:
            report.description = self.data['description'].encode('utf8')
        report.finish_date = pytz.timezone('UTC').localize(datetime.now())
        report.save()

        self.__add_attrs(report)

        if 'resources' in self.data:
            self.__update_parent_resources(report)

        if self.data['id'] == '/':
            if len(ReportComponent.objects.filter(finish_date=None,
                                                  root=self.root)):
                self.__job_failed("There are unfinished reports")
            elif self.job.status != JOB_STATUS[5][0]:
                PSIFinishDecision(self.job)
        return report

    def __create_report_unknown(self, identifier):
        try:
            return ReportUnknown.objects.get(identifier=identifier)
        except ObjectDoesNotExist:
            report = ReportUnknown(identifier=identifier)

        report.parent = self.parent
        report.root = self.root
        if 'description' in self.data:
            report.description = self.data['description'].encode('utf8')
        report.problem_description = self.data['problem desc'].encode('utf8')
        report.component = self.parent.component
        report.save()

        self.__add_attrs(report)
        self.__collect_attrs(report)

        component = report.component
        parent = self.parent
        while parent is not None:
            verdict, created = Verdict.objects.get_or_create(report=parent)
            verdict.unknown += 1
            verdict.save()

            comp_unknown, created = ComponentUnknown.objects.get_or_create(
                report=parent, component=component)
            comp_unknown.number += 1
            comp_unknown.save()

            ReportComponentLeaf.objects.get_or_create(
                report=parent, unknown=report)
            try:
                parent = ReportComponent.objects.get(pk=parent.parent_id)
            except ObjectDoesNotExist:
                parent = None
        ConnectReportWithMarks(report)
        return report

    def __create_report_safe(self, identifier):
        try:
            return ReportSafe.objects.get(identifier=identifier)
        except ObjectDoesNotExist:
            report = ReportSafe(identifier=identifier)

        report.parent = self.parent
        report.root = self.root
        if 'description' in self.data:
            report.description = self.data['description'].encode('utf8')
        report.proof = self.data['proof'].encode('utf8')
        report.save()

        self.__add_attrs(report)
        self.__collect_attrs(report)

        parent = self.parent
        while parent is not None:
            verdict, created = Verdict.objects.get_or_create(report=parent)
            verdict.safe += 1
            verdict.safe_unassociated += 1
            verdict.save()

            ReportComponentLeaf.objects.get_or_create(
                report=parent, safe=report)
            try:
                parent = ReportComponent.objects.get(pk=parent.parent_id)
            except ObjectDoesNotExist:
                parent = None
        ConnectReportWithMarks(report)
        return report

    def __create_report_unsafe(self, identifier):
        try:
            return ReportUnsafe.objects.get(identifier=identifier)
        except ObjectDoesNotExist:
            report = ReportUnsafe(identifier=identifier)

        report.parent = self.parent
        report.root = self.root
        if 'description' in self.data:
            report.description = self.data['description'].encode('utf8')
        report.error_trace = self.data['error trace'].encode('utf8')

        # TODO: get processed trace
        report.error_trace_processed = self.data['error trace'].encode('utf8')
        report.save()

        self.__add_attrs(report)
        self.__collect_attrs(report)

        parent = self.parent
        while parent is not None:
            verdict, created = Verdict.objects.get_or_create(report=parent)
            verdict.unsafe += 1
            verdict.unsafe_unassociated += 1
            verdict.save()

            ReportComponentLeaf.objects.get_or_create(
                report=parent, unsafe=report)
            try:
                parent = ReportComponent.objects.get(pk=parent.parent_id)
            except ObjectDoesNotExist:
                parent = None
        ConnectReportWithMarks(report)
        return report

    def __add_attrs(self, report):
        self.ordered_attrs = []
        for attr in report.attrorder.order_by('id'):
            self.ordered_attrs.append(attr.name.name)
        if 'attrs' not in self.data:
            return
        for attr in save_attrs(self.data['attrs']):
            if not report.attr.filter(pk=attr.pk).exists():
                report.attr.add(attr)
                self.ordered_attrs.append(attr.name.name)
        report.save()

    def __collect_attrs(self, report):
        parent = self.parent
        while parent is not None:
            parent_attrs = []
            for attr in parent.attrorder.order_by('id'):
                parent_attrs.append(attr.name.name)
            self.ordered_attrs = parent_attrs + self.ordered_attrs
            for p_attr in parent.attr.all():
                if not report.attr.filter(pk=p_attr.pk).exists():
                    report.attr.add(p_attr)
            try:
                parent = ReportComponent.objects.get(pk=parent.parent_id)
            except ObjectDoesNotExist:
                parent = None
        report.save()

    def __update_parent_resources(self, report):

        def update_total_resources(rep):
            res_set = rep.resources_cache.filter(~Q(component=None))
            if len(res_set) > 0:
                new_res = Resource()
                if rep.resource is None:
                    new_res.wall_time = 0
                    new_res.cpu_time = 0
                    new_res.memory = 0
                else:
                    new_res.wall_time = rep.resource.wall_time
                    new_res.cpu_time = rep.resource.cpu_time
                    new_res.memory = rep.resource.memory

                for comp_res in res_set:
                    new_res.wall_time += comp_res.resource.wall_time
                    new_res.cpu_time += comp_res.resource.cpu_time
                    new_res.memory = max(comp_res.resource.memory,
                                         new_res.memory)
                new_res.save()
                try:
                    total_compres = rep.resources_cache.get(component=None)
                    total_compres.resource.delete()
                except ObjectDoesNotExist:
                    total_compres = ComponentResource()
                    total_compres.report = rep
                total_compres.resource = new_res
                total_compres.save()

        update_total_resources(report)
        component = report.component

        try:
            report.resources_cache.get(component=component)
        except ObjectDoesNotExist:
            report.resources_cache.create(component=component,
                                          resource=report.resource)

        parent = self.parent
        while parent is not None:
            new_resource = Resource()
            new_resource.wall_time = report.resource.wall_time
            new_resource.cpu_time = report.resource.cpu_time
            new_resource.memory = report.resource.memory
            try:
                compres = parent.resources_cache.get(component=component)
                new_resource.wall_time += compres.resource.wall_time
                new_resource.cpu_time += compres.resource.cpu_time
                new_resource.memory = max(compres.resource.memory,
                                          new_resource.memory)
                compres.resource.delete()
            except ObjectDoesNotExist:
                compres = ComponentResource()
                compres.component = component
                compres.report = parent
            new_resource.save()
            compres.resource = new_resource
            compres.save()
            update_total_resources(parent)
            try:
                parent = ReportComponent.objects.get(pk=parent.parent_id)
            except ObjectDoesNotExist:
                parent = None
