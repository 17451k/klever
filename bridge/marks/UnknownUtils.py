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
import json

from django.db.models import ProtectedError
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
from django.utils.translation import ugettext_lazy as _

from bridge.vars import USER_ROLES, MARK_STATUS, MARK_TYPE, ASSOCIATION_TYPE
from bridge.utils import unique_id, BridgeException, logger, ArchiveFileContent

from users.models import User
from reports.models import ReportUnknown, ReportComponentLeaf, Component
from marks.models import MarkUnknown, MarkUnknownHistory, MarkUnknownReport, UnknownProblem, ComponentMarkUnknownProblem


class NewMark:
    def __init__(self, user, args):
        self._user = user
        self._args = args
        self.changes = {}
        self.__check_args()

    def __check_args(self):
        if not isinstance(self._args, dict):
            raise ValueError('Wrong type: args (%s)' % type(self._args))
        if not isinstance(self._user, User):
            raise ValueError('Wrong type: user (%s)' % type(self._user))
        if self._args.get('status') not in set(x[0] for x in MARK_STATUS):
            raise ValueError('Unsupported status: %s' % self._args.get('status'))
        if not isinstance(self._args.get('comment'), str):
            self._args['comment'] = ''

        if self._user.extended.role != USER_ROLES[2][0]:
            self._args['is_modifiable'] = MarkUnknown._meta.get_field('is_modifiable').default
        elif not isinstance(self._args.get('is_modifiable'), bool):
            raise ValueError('Wrong type: is_modifiable (%s)' % type(self._args.get('is_modifiable')))

        if 'function' not in self._args or len(self._args['function']) == 0:
            raise BridgeException(_('The pattern is required'))
        try:
            re.search(self._args['function'], '')
        except Exception as e:
            logger.exception("Wrong mark function (%s): %s" % (self._args['function'], e), stack_info=True)
            raise BridgeException(_('The pattern is wrong, please refer to documentation on the standard Python '
                                    'library for processing reqular expressions'))

        if 'problem' not in self._args or len(self._args['problem']) == 0:
            raise BridgeException(_('The problem is required'))
        elif len(self._args['problem']) > 15:
            raise BridgeException(_('The problem length must be less than 15 characters'))

        if 'link' not in self._args or len(self._args['link']) == 0:
            self._args['link'] = None

    def create_mark(self, report):
        if MarkUnknown.objects.filter(component=report.component, problem_pattern=self._args['problem']).count() > 0:
            raise BridgeException(_('Could not create a new mark since the similar mark exists already'))

        mark = MarkUnknown.objects.create(
            identifier=unique_id(), author=self._user, format=report.root.job.format,
            job=report.root.job, description=str(self._args.get('description', '')), status=self._args['status'],
            is_modifiable=self._args['is_modifiable'], component=report.component, function=self._args['function'],
            problem_pattern=self._args['problem'], link=self._args['link']
        )
        try:
            self.__create_version(mark)
        except Exception:
            mark.delete()
            raise
        self.changes = ConnectMark(mark, prime_id=report.id).changes
        return mark

    def change_mark(self, mark, recalculate_cache=True):
        if len(self._args['comment']) == 0:
            raise BridgeException(_('Change comment is required'))

        if MarkUnknown.objects.filter(component=mark.component, problem_pattern=self._args['problem']) \
                .exclude(id=mark.id).count() > 0:
            raise BridgeException(_('Could not change the mark since it would be similar to the existing mark'))

        do_recalc = (self._args['function'] != mark.function or self._args['problem'] != mark.problem_pattern)

        mark.author = self._user
        mark.status = self._args['status']
        mark.description = str(self._args.get('description', ''))
        mark.version += 1
        mark.is_modifiable = self._args['is_modifiable']
        mark.link = self._args['link']
        mark.function = self._args['function']
        mark.problem_pattern = self._args['problem']
        self.__create_version(mark)
        mark.save()

        if recalculate_cache:
            if do_recalc:
                self.changes = ConnectMark(mark).changes
            else:
                self.changes = self.__create_changes(mark)
        return mark

    def upload_mark(self):
        if 'component' not in self._args or len(self._args['component']) == 0:
            raise BridgeException(_("Component name is required"))
        if len(self._args['component']) > 15:
            raise BridgeException(_("Component name is too long"))
        component = Component.objects.get_or_create(name=self._args['component'])[0]
        if 'format' not in self._args:
            raise BridgeException(_('Unknown mark format is required'))
        if isinstance(self._args.get('identifier'), str) and 0 < len(self._args['identifier']) < 255:
            if MarkUnknown.objects.filter(identifier=self._args['identifier']).count() > 0:
                raise BridgeException(_("The mark with identifier specified in the archive already exists"))
        else:
            self._args['identifier'] = unique_id()
        if MarkUnknown.objects.filter(component=component, problem_pattern=self._args['problem']).count() > 0:
            raise BridgeException(_('Could not change the mark since it would be similar to the existing mark'))
        mark = MarkUnknown.objects.create(
            identifier=self._args['identifier'], author=self._user, description=str(self._args.get('description', '')),
            status=self._args['status'], is_modifiable=self._args['is_modifiable'],
            problem_pattern=self._args['problem'], function=self._args['function'], link=self._args['link'],
            component=component, format=self._args['format'], type=MARK_TYPE[2][0]
        )
        try:
            self.__create_version(mark)
        except Exception:
            mark.delete()
            raise
        return mark

    def __create_changes(self, mark):
        self.__is_not_used()
        changes = {}
        for mr in mark.markreport_set.all().select_related('report'):
            changes[mr.report] = {'kind': '='}
        return changes

    def __create_version(self, mark):
        return MarkUnknownHistory.objects.create(
            mark=mark, version=mark.version, status=mark.status, description=mark.description,
            change_date=mark.change_date, comment=self._args['comment'], author=mark.author,
            function=mark.function, problem_pattern=mark.problem_pattern, link=mark.link
        )

    def __is_not_used(self):
        pass


class ConnectMark:
    def __init__(self, mark, prime_id=None):
        self.mark = mark
        self._prime_id = prime_id
        self.changes = {}
        self.__connect_unknown_mark()

    def __connect_unknown_mark(self):
        for mark_unknown in self.mark.markreport_set.all():
            self.changes[mark_unknown.report] = {'kind': '-'}
        self.mark.markreport_set.all().delete()
        new_markreports = []
        problems = {}
        for unknown in ReportUnknown.objects.filter(component=self.mark.component):
            try:
                problem_description = ArchiveFileContent(unknown, unknown.problem_description).content.decode('utf8')
            except Exception as e:
                logger.exception("Can't get problem description for unknown '%s': %s" % (unknown.id, e))
                return
            problem = MatchUnknown(problem_description, self.mark.function, self.mark.problem_pattern).problem
            if problem is None:
                continue
            elif len(problem) > 15:
                problem = 'Too long!'
                logger.error("Problem '%s' for mark %s is too long" % (problem, self.mark.identifier), stack_info=True)
            if problem not in problems:
                problems[problem] = UnknownProblem.objects.get_or_create(name=problem)[0]
            ass_type = ASSOCIATION_TYPE[0][0]
            if self._prime_id == unknown.id:
                ass_type = ASSOCIATION_TYPE[1][0]
            new_markreports.append(MarkUnknownReport(
                mark=self.mark, report=unknown, problem=problems[problem], type=ass_type, author=self.mark.author
            ))
            if unknown in self.changes:
                self.changes[unknown]['kind'] = '='
            else:
                self.changes[unknown] = {'kind': '+'}
        MarkUnknownReport.objects.bulk_create(new_markreports)
        update_unknowns_cache(list(self.changes))


class ConnectReport:
    def __init__(self, report, update_cache=True):
        self._update_cache = update_cache
        self.report = report
        self.__connect()

    def __connect(self):
        self.report.markreport_set.all().delete()

        try:
            problem_desc = ArchiveFileContent(self.report, self.report.problem_description).content.decode('utf8')
        except Exception as e:
            logger.exception("Can't get problem desc for unknown '%s': %s" % (self.report.id, e))
            return
        new_markreports = []
        problems = {}
        for mark in MarkUnknown.objects.filter(component=self.report.component):
            problem = MatchUnknown(problem_desc, mark.function, mark.problem_pattern).problem
            if problem is None:
                continue
            elif len(problem) > 15:
                problem = 'Too long!'
                logger.error(
                    "Generated problem '%s' for mark %s is too long" % (problem, mark.identifier), stack_info=True
                )
            if problem not in problems:
                problems[problem] = UnknownProblem.objects.get_or_create(name=problem)[0]
            new_markreports.append(MarkUnknownReport(mark=mark, report=self.report, problem=problems[problem]))
        MarkUnknownReport.objects.bulk_create(new_markreports)
        if self._update_cache:
            update_unknowns_cache([self.report])


class RecalculateConnections:
    def __init__(self, roots):
        self._roots = roots
        self.__recalc()
        for problem in UnknownProblem.objects.all():
            try:
                problem.delete()
            except ProtectedError:
                pass

    def __recalc(self):
        MarkUnknownReport.objects.filter(report__root__in=self._roots).delete()
        ComponentMarkUnknownProblem.objects.filter(report__root__in=self._roots).delete()
        # TODO: optiomizations: connect all reports at once
        for unknown in ReportUnknown.objects.filter(root__in=self._roots):
            ConnectReport(unknown, False)
        update_unknowns_cache(ReportUnknown.objects.filter(root__in=self._roots))


class MatchUnknown:
    def __init__(self, description, func, pattern):
        self.description = str(description)
        self.function = str(func)
        self.pattern = str(pattern)
        self.max_pn = None
        self.numbers = []
        self.__check_pattern()
        self.problem = self.__match_description()
        if isinstance(self.problem, str) and len(self.problem) == 0:
            self.problem = None

    def __check_pattern(self):
        self.numbers = re.findall('{(\d+)}', self.pattern)
        self.numbers = [int(x) for x in self.numbers]
        self.max_pn = -1
        if len(self.numbers) > 0:
            self.max_pn = max(self.numbers)
        for n in range(self.max_pn + 1):
            if n not in self.numbers:
                self.max_pn = None
                self.numbers = []
                return

    def __match_description(self):
        for l in self.description.split('\n'):
            try:
                m = re.search(self.function, l)
            except Exception as e:
                logger.exception("Regexp error: %s" % e, stack_info=True)
                return None
            if m is not None:
                if self.max_pn is not None and len(self.numbers) > 0:
                    group_elements = []
                    for n in range(1, self.max_pn + 2):
                        try:
                            group_elements.append(m.group(n))
                        except IndexError:
                            group_elements.append('')
                    return self.pattern.format(*group_elements)
                return self.pattern
        return None


class PopulateMarks:
    def __init__(self, manager):
        self.total = 0
        self.created = 0
        self.__populate(manager)

    def __populate(self, manager):
        presets_dir = os.path.join(settings.BASE_DIR, 'marks', 'presets', 'unknowns')
        for component_dir in [os.path.join(presets_dir, x) for x in os.listdir(presets_dir)]:
            component = os.path.basename(component_dir)
            if not 0 < len(component) <= 15:
                raise ValueError('Wrong component length: "%s". 1-15 is allowed.' % component)
            for mark_settings in [os.path.join(component_dir, x) for x in os.listdir(component_dir)]:
                data = None
                with open(mark_settings, encoding='utf8') as fp:
                    try:
                        data = json.load(fp)
                    except Exception as e:
                        fp.seek(0)
                        try:
                            path_to_json = os.path.abspath(os.path.join(component_dir, fp.read()))
                            with open(path_to_json, encoding='utf8') as fp2:
                                data = json.load(fp2)
                        except Exception:
                            raise BridgeException("Can't parse json data of unknown mark: %s (\"%s\")" % (
                                e, os.path.relpath(mark_settings, presets_dir)
                            ))
                if not isinstance(data, dict) or any(x not in data for x in ['function', 'pattern']):
                    raise BridgeException('Wrong unknown mark data format: %s' % mark_settings)
                try:
                    re.compile(data['function'])
                except re.error:
                    raise ValueError('Wrong regular expression: "%s"' % data['function'])
                if 'link' not in data:
                    data['link'] = ''
                if 'description' not in data:
                    data['description'] = ''
                if 'status' not in data:
                    data['status'] = MARK_STATUS[0][0]
                if 'is_modifiable' not in data:
                    data['is_modifiable'] = True
                if data['status'] not in list(x[0] for x in MARK_STATUS) or len(data['function']) == 0 \
                        or not 0 < len(data['pattern']) <= 15 or not isinstance(data['is_modifiable'], bool):
                    raise BridgeException('Wrong unknown mark data: %s' % mark_settings)
                self.total += 1
                try:
                    MarkUnknown.objects.get(component__name=component, problem_pattern=data['pattern'])
                except ObjectDoesNotExist:
                    mark = MarkUnknown.objects.create(
                        identifier=unique_id(), component=Component.objects.get_or_create(name=component)[0],
                        author=manager, status=data['status'], is_modifiable=data['is_modifiable'],
                        function=data['function'], problem_pattern=data['pattern'], description=data['description'],
                        type=MARK_TYPE[1][0], link=data['link'] if len(data['link']) > 0 else None
                    )
                    MarkUnknownHistory.objects.create(
                        mark=mark, version=mark.version, author=mark.author, status=mark.status,
                        function=mark.function, problem_pattern=mark.problem_pattern, link=mark.link,
                        change_date=mark.change_date, description=mark.description, comment=''
                    )
                    ConnectMark(mark)
                    self.created += 1
                except MultipleObjectsReturned:
                    raise Exception('There are similar unknown marks in the system')


def update_unknowns_cache(unknowns):
    reports = set()
    for leaf in ReportComponentLeaf.objects.filter(unknown__in=list(unknowns)):
        reports.add(leaf.report_id)

    all_unknowns = {}
    components_data = {}
    for leaf in ReportComponentLeaf.objects.filter(report_id__in=reports).exclude(unknown=None)\
            .values('report_id', 'unknown_id', 'unknown__component_id'):
        if leaf['report_id'] not in all_unknowns:
            all_unknowns[leaf['report_id']] = set()
        all_unknowns[leaf['report_id']].add(leaf['unknown_id'])
        if leaf['unknown__component_id'] not in components_data:
            components_data[leaf['unknown__component_id']] = set()
        components_data[leaf['unknown__component_id']].add(leaf['unknown_id'])

    unknowns_ids = set()
    for rc_id in all_unknowns:
        unknowns_ids = unknowns_ids | all_unknowns[rc_id]
    marked_unknowns = set()
    problems_data = {}
    for mr in MarkUnknownReport.objects.filter(report_id__in=unknowns_ids):
        if mr.problem_id not in problems_data:
            problems_data[mr.problem_id] = set()
        problems_data[mr.problem_id].add(mr.report_id)
        marked_unknowns.add(mr.report_id)

    problems_data[None] = unknowns_ids - marked_unknowns

    new_cache = []
    for r_id in all_unknowns:
        for p_id in problems_data:
            for c_id in components_data:
                number = len(all_unknowns[r_id] & problems_data[p_id] & components_data[c_id])
                if number > 0:
                    new_cache.append(ComponentMarkUnknownProblem(
                        report_id=r_id, component_id=c_id, problem_id=p_id, number=number
                    ))
    ComponentMarkUnknownProblem.objects.filter(report_id__in=reports).delete()
    ComponentMarkUnknownProblem.objects.bulk_create(new_cache)


def delete_marks(marks):
    changes = {}
    for mark in marks:
        changes[mark.id] = {}
    MarkUnknown.objects.filter(id__in=changes).update(version=0)
    for mr in MarkUnknownReport.objects.filter(mark__in=marks).select_related('report'):
        changes[mr.mark_id][mr.report] = {'kind': '-'}
    MarkUnknown.objects.filter(id__in=changes).delete()
    unknowns_changes = {}
    for m_id in changes:
        for report in changes[m_id]:
            unknowns_changes[report] = changes[m_id][report]
    update_unknowns_cache(unknowns_changes)
    return unknowns_changes
