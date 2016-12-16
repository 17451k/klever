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

import re
import json
from django.core.exceptions import ObjectDoesNotExist
from django.core.urlresolvers import reverse
from django.db.models import Count
from django.utils.translation import ugettext_lazy as _
from bridge.utils import logger
from bridge.vars import JOB_STATUS, JOBS_COMPARE_ATTRS
from jobs.utils import JobAccess, CompareFileSet
from reports.models import *
from marks.models import MarkUnsafeReport, MarkSafeReport, MarkUnknownReport
from marks.tables import UNSAFE_COLOR, SAFE_COLOR


def can_compare(user, job1, job2):
    if not isinstance(job1, Job) or not isinstance(job2, Job) or not isinstance(user, User):
        return False
    if job1.type != job2.type:
        return False
    if not JobAccess(user, job1).can_view() or job1.status != JOB_STATUS[3][0]:
        return False
    if not JobAccess(user, job2).can_view() or job2.status != JOB_STATUS[3][0]:
        return False
    return True


class ReportTree(object):
    def __init__(self, job):
        self.job = job
        self.name_ids = self.__get_attr_names()
        self.attr_values = {}
        self._leaves_data = {'u': {}, 's': {}, 'f': {}}
        self.__get_tree()

    def __get_attr_names(self):
        return list(x.id for x in AttrName.objects.filter(name__in=JOBS_COMPARE_ATTRS[self.job.type]).only('id'))

    def __get_tree(self):
        leaves_fields = {
            'u': 'unsafe_id',
            's': 'safe_id',
            'f': 'unknown_id'
        }
        for leaf in ReportComponentLeaf.objects.filter(report__root__job=self.job).select_related('report')\
                .only('report__parent_id', *leaves_fields.values()):
            for l_type in leaves_fields:
                l_id = leaf.__getattribute__(leaves_fields[l_type])
                if l_id is not None:
                    if l_id not in self._leaves_data[l_type]:
                        self._leaves_data[l_type][l_id] = {}
                    self._leaves_data[l_type][l_id][leaf.report_id] = leaf.report.parent_id
                    break

        # The order is important
        for l_type in 'usf':
            self.__fill_leaves_vals(l_type)

    def __fill_leaves_vals(self, l_type):
        leaves_tables = {
            'u': ReportUnsafe,
            's': ReportSafe,
            'f': ReportUnknown
        }

        leaves = {}
        for r in leaves_tables[l_type].objects.filter(root__job=self.job).only('id', 'parent_id'):
            leaves[r.id] = r.parent_id

        leaves_attrs = {}
        for ra in ReportAttr.objects.filter(report_id__in=list(leaves), attr__name_id__in=self.name_ids)\
                .select_related('attr').only('report_id', 'attr__name_id', 'attr__value'):
            if ra.report_id not in leaves_attrs:
                leaves_attrs[ra.report_id] = {}
            leaves_attrs[ra.report_id][ra.attr.name_id] = ra.attr.value

        for l_id in leaves:
            if l_id not in leaves_attrs or any(name_id not in leaves_attrs[l_id] for name_id in self.name_ids):
                continue
            attrs_id = json.dumps(list(leaves_attrs[l_id][name_id] for name_id in self.name_ids), ensure_ascii=False)

            branch_ids = [(l_type, l_id)]
            parent = leaves[l_id]
            while parent is not None:
                branch_ids.insert(0, ('c', parent))
                parent = self._leaves_data[l_type][l_id][parent]

            if attrs_id in self.attr_values:
                if l_type == 's':
                    raise ValueError('Too many leaf reports for "%s"' % attrs_id)
                elif l_type == 'f':
                    for branch in self.attr_values[attrs_id]['branches']:
                        if branch[-1][0] != 'u':
                            raise ValueError('Too many leaf reports for "%s"' % attrs_id)
                    self.attr_values[attrs_id]['verdict'] = COMPARE_VERDICT[2][0]
                self.attr_values[attrs_id]['branches'].append(branch_ids)
            else:
                if l_type == 'u':
                    verdict = COMPARE_VERDICT[1][0]
                elif l_type == 's':
                    verdict = COMPARE_VERDICT[0][0]
                else:
                    verdict = COMPARE_VERDICT[3][0]
                self.attr_values[attrs_id] = {'branches': [branch_ids], 'verdict': verdict}

        del self._leaves_data[l_type]


class CompareTree(object):
    def __init__(self, user, j1, j2):
        self.user = user
        self.tree1 = ReportTree(j1)
        self.tree2 = ReportTree(j2)
        self.attr_values = {}
        self.__compare_values()
        self.__fill_cache(j1, j2)

    def __compare_values(self):
        for a_id in self.tree1.attr_values:
            self.attr_values[a_id] = {
                'v1': self.tree1.attr_values[a_id]['verdict'],
                'v2': COMPARE_VERDICT[4][0],
                'branches1': self.tree1.attr_values[a_id]['branches'],
                'branches2': []
            }
            if a_id in self.tree2.attr_values:
                self.attr_values[a_id]['v2'] = self.tree2.attr_values[a_id]['verdict']
                self.attr_values[a_id]['branches2'] = self.tree2.attr_values[a_id]['branches']
        for a_id in self.tree2.attr_values:
            if a_id not in self.tree1.attr_values:
                self.attr_values[a_id] = {
                    'v1': COMPARE_VERDICT[4][0],
                    'v2': self.tree2.attr_values[a_id]['verdict'],
                    'branches1': [],
                    'branches2': self.tree2.attr_values[a_id]['branches']
                }

    def __fill_cache(self, j1, j2):
        CompareJobsInfo.objects.filter(user=self.user).delete()
        info = CompareJobsInfo.objects.create(
            user=self.user, root1=j1.reportroot, root2=j2.reportroot,
            files_diff=json.dumps(CompareFileSet(j1, j2).data, ensure_ascii=False)
        )
        CompareJobsCache.objects.bulk_create(list(CompareJobsCache(
            info=info, attr_values=x,
            verdict1=self.attr_values[x]['v1'], verdict2=self.attr_values[x]['v2'],
            reports1=json.dumps(self.attr_values[x]['branches1'], ensure_ascii=False),
            reports2=json.dumps(self.attr_values[x]['branches2'], ensure_ascii=False)
        ) for x in self.attr_values))


class ComparisonTableData(object):
    def __init__(self, user, j1, j2):
        self.job1 = j1
        self.job2 = j2
        self.user = user
        self.data = []
        self.error = None
        self.info = 0
        self.attrs = []
        self.__get_data()

    def __get_data(self):
        try:
            info = CompareJobsInfo.objects.get(user=self.user, root1=self.job1.reportroot, root2=self.job2.reportroot)
        except ObjectDoesNotExist:
            self.error = _('The comparison cache was not found')
            return
        self.info = info.pk

        numbers = {}
        for c in CompareJobsCache.objects.filter(info=info).values('verdict1', 'verdict2').annotate(number=Count('id')):
            numbers[(c['verdict1'], c['verdict2'])] = c['number']

        for v1 in COMPARE_VERDICT:
            row_data = []
            for v2 in COMPARE_VERDICT:
                num = '-'
                if (v1[0], v2[0]) in numbers:
                    num = (numbers[(v1[0], v2[0])], v2[0])
                row_data.append(num)
            self.data.append(row_data)
        all_attrs = {}
        for compare in info.comparejobscache_set.all():
            try:
                attr_values = json.loads(compare.attr_values)
            except Exception as e:
                logger.exception("Json parsing error: %s" % e, stack_info=True)
                self.error = 'Unknown error'
                return
            if len(attr_values) != len(JOBS_COMPARE_ATTRS[info.root1.job.type]):
                self.error = 'Unknown error'
                return
            for i in range(len(attr_values)):
                if JOBS_COMPARE_ATTRS[info.root1.job.type][i] not in all_attrs:
                    all_attrs[JOBS_COMPARE_ATTRS[info.root1.job.type][i]] = []
                if attr_values[i] not in all_attrs[JOBS_COMPARE_ATTRS[info.root1.job.type][i]]:
                    all_attrs[JOBS_COMPARE_ATTRS[info.root1.job.type][i]].append(attr_values[i])

        for a in JOBS_COMPARE_ATTRS[info.root1.job.type]:
            if a in all_attrs:
                self.attrs.append({'name': a, 'values': list(sorted(all_attrs[a]))})


class ComparisonData(object):
    def __init__(self, info_id, page_num, hide_attrs, hide_components, verdict=None, attrs=None):
        self.error = None
        try:
            self.info = CompareJobsInfo.objects.get(pk=info_id)
        except ObjectDoesNotExist:
            self.error = _("The comparison cache was not found")
            return
        self.v1 = self.v2 = None
        self.hide_attrs = hide_attrs
        self.hide_components = hide_components
        self.attr_search = False
        self.pages = {
            'backward': True,
            'forward': True,
            'num': page_num,
            'total': 0
        }
        self.data = self.__get_data(verdict, attrs)

    def __get_verdicts(self, verdict):
        m = re.match('^(\d)_(\d)$', verdict)
        if m is None:
            self.error = 'Unknown error'
            return None, None
        v1 = m.group(1)
        v2 = m.group(2)
        if any(v not in list(x[0] for x in COMPARE_VERDICT) for v in [v1, v2]):
            self.error = 'Unknown error'
            return None, None
        return v1, v2

    def __get_data(self, verdict=None, search_attrs=None):
        if search_attrs is not None:
            try:
                search_attrs = json.dumps(json.loads(search_attrs), ensure_ascii=False)
            except ValueError:
                self.error = 'Unknown error'
                return None
            if '__REGEXP_ANY__' in search_attrs:
                search_attrs = re.escape(search_attrs)
                search_attrs = search_attrs.replace('__REGEXP_ANY__', '[^,]+')
                search_attrs = '^' + search_attrs + '$'
                data = self.info.comparejobscache_set.filter(attr_values__regex=search_attrs).order_by('id')
            else:
                data = self.info.comparejobscache_set.filter(attr_values=search_attrs).order_by('id')
            self.attr_search = True
        elif verdict is not None:
            (v1, v2) = self.__get_verdicts(verdict)
            data = self.info.comparejobscache_set.filter(verdict1=v1, verdict2=v2).order_by('id')
        else:
            self.error = 'Unknown error'
            return None
        self.pages['total'] = len(data)
        if self.pages['total'] < self.pages['num']:
            self.error = _('Required reports were not found')
            return None
        self.pages['backward'] = (self.pages['num'] > 1)
        self.pages['forward'] = (self.pages['num'] < self.pages['total'])
        data = data[self.pages['num'] - 1]
        self.v1 = data.verdict1
        self.v2 = data.verdict2

        try:
            branches = self.__compare_reports(data)
        except ObjectDoesNotExist:
            self.error = _('The report was not found, please recalculate the comparison cache')
            return None
        if branches is None:
            if self.error is None:
                self.error = 'Unknown error'
            return None

        final_data = []
        for branch in branches:
            ordered = []
            for i in sorted(list(branch)):
                if len(branch[i]) > 0:
                    ordered.append(branch[i])
            final_data.append(ordered)
        return final_data

    def __compare_reports(self, c):
        data1 = self.__get_reports_data(json.loads(c.reports1))
        if data1 is None:
            if self.error is None:
                self.error = 'Unknown error'
            return None
        data2 = self.__get_reports_data(json.loads(c.reports2))
        if data2 is None:
            if self.error is None:
                self.error = 'Unknown error'
            return None
        for i in sorted(list(data1)):
            if i not in data2:
                break
            blocks = self.__compare_lists(data1[i], data2[i])
            if isinstance(blocks, list) and len(blocks) == 2:
                data1[i] = blocks[0]
                data2[i] = blocks[1]
        return [data1, data2]

    def __compare_lists(self, blocks1, blocks2):
        for b1 in blocks1:
            for b2 in blocks2:
                if b1.block_class != b2.block_class or b1.type == 'm':
                    continue
                for a1 in b1.list:
                    if a1['name'] not in list(x['name'] for x in b2.list):
                        a1['color'] = '#c60806'
                    for a2 in b2.list:
                        if a2['name'] not in list(x['name'] for x in b1.list):
                            a2['color'] = '#c60806'
                        if a1['name'] == a2['name'] and a1['value'] != a2['value']:
                            a1['color'] = a2['color'] = '#af49bd'
        if self.hide_attrs:
            for b1 in blocks1:
                for b2 in blocks2:
                    if b1.block_class != b2.block_class or b1.type == 'm':
                        continue
                    for b in [b1, b2]:
                        new_list = []
                        for a in b.list:
                            if 'color' in a:
                                new_list.append(a)
                        b.list = new_list
        if self.hide_components:
            for_del = {
                'b1': [],
                'b2': []
            }
            for i in range(len(blocks1)):
                for j in range(len(blocks2)):
                    if blocks1[i].block_class != blocks2[j].block_class or blocks1[i].type != 'c':
                        continue
                    if blocks1[i].list == blocks2[j].list and blocks1[i].add_info == blocks2[j].add_info:
                        for_del['b1'].append(i)
                        for_del['b2'].append(j)
            new_blocks1 = []
            for i in range(0, len(blocks1)):
                if i not in for_del['b1']:
                    new_blocks1.append(blocks1[i])
            new_blocks2 = []
            for i in range(0, len(blocks2)):
                if i not in for_del['b2']:
                    new_blocks2.append(blocks2[i])
            return [new_blocks1, new_blocks2]
        return None

    def __get_reports_data(self, reports):
        branch_data = {}
        get_block = {
            'u': (self.__unsafe_data, self.__unsafe_mark_data),
            's': (self.__safe_data, self.__safe_mark_data),
            'f': (self.__unknown_data, self.__unknown_mark_data)
        }
        added_ids = set()
        for branch in reports:
            cnt = 1
            parent = None
            for rdata in branch:
                if cnt not in branch_data:
                    branch_data[cnt] = []
                if rdata[1] in added_ids:
                    pass
                elif rdata[0] == 'c':
                    branch_data[cnt].append(
                        self.__component_data(rdata[1], parent)
                    )
                elif rdata[0] in 'usf':
                    branch_data[cnt].append(
                        get_block[rdata[0]][0](rdata[1], parent)
                    )
                    if self.v1 == self.v2:
                        cnt += 1
                        for b in get_block[rdata[0]][1](rdata[1]):
                            if cnt not in branch_data:
                                branch_data[cnt] = []
                            if b.id not in list(x.id for x in branch_data[cnt]):
                                branch_data[cnt].append(b)
                            else:
                                for i in range(len(branch_data[cnt])):
                                    if b.id == branch_data[cnt][i].id:
                                        if rdata[0] == 'f' \
                                                and b.add_info[0]['value'] != branch_data[cnt][i].add_info[0]['value']:
                                            branch_data[cnt].append(b)
                                        else:
                                            branch_data[cnt][i].parents.extend(b.parents)
                                        break
                    break
                parent = rdata[1]
                cnt += 1
                added_ids.add(rdata[1])
        return branch_data

    def __component_data(self, report_id, parent_id):
        report = ReportComponent.objects.get(pk=report_id)
        block = CompareBlock('c_%s' % report_id, 'c', report.component.name, 'comp_%s' % report.component_id)
        if parent_id is not None:
            block.parents.append('c_%s' % parent_id)
        for a in report.attrs.select_related('attr', 'attr__name').order_by('attr__name__name'):
            attr_data = {
                'name': a.attr.name.name,
                'value': a.attr.value
            }
            if attr_data['name'] in JOBS_COMPARE_ATTRS[self.info.root1.job.type]:
                attr_data['color'] = '#8bb72c'
            block.list.append(attr_data)
        block.href = reverse('reports:component', args=[report.root.job_id, report.pk])
        return block

    def __unsafe_data(self, report_id, parent_id):
        report = ReportUnsafe.objects.get(pk=report_id)
        block = CompareBlock('u_%s' % report_id, 'u', _('Unsafe'), 'unsafe')
        block.parents.append('c_%s' % parent_id)
        block.add_info = {'value': report.get_verdict_display(), 'color': UNSAFE_COLOR[report.verdict]}
        for a in report.attrs.select_related('attr', 'attr__name').order_by('attr__name__name'):
            attr_data = {
                'name': a.attr.name.name,
                'value': a.attr.value
            }
            if attr_data['name'] in JOBS_COMPARE_ATTRS[self.info.root1.job.type]:
                attr_data['color'] = '#8bb72c'
            block.list.append(attr_data)
        block.href = reverse('reports:leaf', args=['unsafe', report.pk])
        return block

    def __safe_data(self, report_id, parent_id):
        report = ReportSafe.objects.get(pk=report_id)
        block = CompareBlock('s_%s' % report_id, 's', _('Safe'), 'safe')
        block.parents.append('c_%s' % parent_id)
        block.add_info = {'value': report.get_verdict_display(), 'color': SAFE_COLOR[report.verdict]}
        for a in report.attrs.select_related('attr', 'attr__name').order_by('attr__name__name'):
            attr_data = {
                'name': a.attr.name.name,
                'value': a.attr.value
            }
            if attr_data['name'] in JOBS_COMPARE_ATTRS[self.info.root1.job.type]:
                attr_data['color'] = '#8bb72c'
            block.list.append(attr_data)
        block.href = reverse('reports:leaf', args=['safe', report.pk])
        return block

    def __unknown_data(self, report_id, parent_id):
        report = ReportUnknown.objects.get(pk=report_id)
        block = CompareBlock('f_%s' % report_id, 'f', _('Unknown'), 'unknown-%s' % report.component.name)
        block.parents.append('c_%s' % parent_id)
        problems = list(x.problem.name for x in report.markreport_set.select_related('problem').order_by('id'))
        if len(problems) > 0:
            block.add_info = {
                'value': '; '.join(problems),
                'color': '#c60806'
            }
        else:
            block.add_info = {'value': _('Without marks')}
        for a in report.attrs.select_related('attr', 'attr__name').order_by('attr__name__name'):
            attr_data = {
                'name': a.attr.name.name,
                'value': a.attr.value
            }
            if attr_data['name'] in JOBS_COMPARE_ATTRS[self.info.root1.job.type]:
                attr_data['color'] = '#8bb72c'
            block.list.append(attr_data)
        block.href = reverse('reports:leaf', args=['unknown', report.pk])
        return block

    def __unsafe_mark_data(self, report_id):
        self.__is_not_used()
        blocks = []
        for mark in MarkUnsafeReport.objects.filter(report_id=report_id).select_related('mark'):
            block = CompareBlock('um_%s' % mark.mark_id, 'm', _('Unsafes mark'))
            block.parents.append('u_%s' % report_id)
            block.add_info = {'value': mark.mark.get_verdict_display(), 'color': UNSAFE_COLOR[mark.mark.verdict]}
            block.href = reverse('marks:view_mark', args=['unsafe', mark.mark_id])
            for t in mark.mark.versions.order_by('-version').first().tags.all():
                block.list.append({'name': None, 'value': t.tag.tag})
            blocks.append(block)
        return blocks

    def __safe_mark_data(self, report_id):
        self.__is_not_used()
        blocks = []
        for mark in MarkSafeReport.objects.filter(report_id=report_id).select_related('mark'):
            block = CompareBlock('sm_%s' % mark.mark_id, 'm', _('Safes mark'))
            block.parents.append('s_%s' % report_id)
            block.add_info = {'value': mark.mark.get_verdict_display(), 'color': SAFE_COLOR[mark.mark.verdict]}
            block.href = reverse('marks:view_mark', args=['safe', mark.mark_id])
            for t in mark.mark.versions.order_by('-version').first().tags.all():
                block.list.append({'name': None, 'value': t.tag.tag})
            blocks.append(block)
        return blocks

    def __unknown_mark_data(self, report_id):
        self.__is_not_used()
        blocks = []
        for mark in MarkUnknownReport.objects.filter(report_id=report_id).select_related('problem'):
            block = CompareBlock("fm_%s" % mark.mark_id, 'm', _('Unknowns mark'))
            block.parents.append('f_%s' % report_id)
            block.add_info = {'value': mark.problem.name}
            block.href = reverse('marks:view_mark', args=['unknown', mark.mark_id])
            blocks.append(block)
        return blocks

    def __is_not_used(self):
        pass


class CompareBlock(object):
    def __init__(self, block_id, block_type, title, block_class=None):
        self.id = block_id
        self.block_class = block_class if block_class is not None else self.id
        self.type = block_type
        self.title = title
        self.parents = []
        self.list = []
        self.add_info = None
        self.href = None
