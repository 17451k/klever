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

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from django.utils.translation import ugettext as _, activate
from bridge.vars import USER_ROLES
from jobs.models import Job, JobFile
from reports.models import Component, Computer
from marks.models import UnknownProblem, ConvertedTraces
from tools.utils import objects_without_relations, ClearFiles, Recalculation
from tools.profiling import unparallel_group, ProfileData


@login_required
def manager_tools(request):
    activate(request.user.extended.language)
    return render(request, "tools/ManagerPanel.html", {
        'components': Component.objects.all(),
        'problems': UnknownProblem.objects.all(),
        'jobs': Job.objects.filter(light=False)
    })


@login_required
@unparallel_group([Component])
def rename_component(request):
    activate(request.user.extended.language)
    if request.method != 'POST':
        return JsonResponse({'error': _('Unknown error')})
    if request.user.extended.role != USER_ROLES[2][0]:
        return JsonResponse({'error': _("No access")})
    try:
        component = Component.objects.get(pk=int(request.POST.get('component_id', 0)))
    except ObjectDoesNotExist:
        return JsonResponse({'error': _("The component was not found")})
    new_name = request.POST.get('name', '')
    if len(new_name) == 0 or len(new_name) > 15:
        return JsonResponse({'error': _("The component name should be greater than 0 and less than 16 symbols")})
    if Component.objects.filter(name=new_name).exclude(pk=component.pk).count() > 0:
        return JsonResponse({'error': _("The specified component name is used already")})
    component.name = new_name
    component.save()
    return JsonResponse({'message': _("The component was successfully renamed")})


@login_required
@unparallel_group([Component])
def clear_components(request):
    activate(request.user.extended.language)
    if request.method != 'POST':
        return JsonResponse({'error': _('Unknown error')})
    if request.user.extended.role != USER_ROLES[2][0]:
        return JsonResponse({'error': _("No access")})
    objects_without_relations(Component).delete()
    return JsonResponse({'message': _("All unused components were deleted, please reload the page")})


@login_required
@unparallel_group([UnknownProblem])
def clear_problems(request):
    activate(request.user.extended.language)
    if request.method != 'POST':
        return JsonResponse({'error': _('Unknown error')})
    if request.user.extended.role != USER_ROLES[2][0]:
        return JsonResponse({'error': _("No access")})
    objects_without_relations(UnknownProblem).delete()
    return JsonResponse({'message': _("All unused problems were deleted, please reload the page")})


@login_required
@unparallel_group([JobFile, ConvertedTraces, Computer, Component, UnknownProblem])
def clear_system(request):
    activate(request.user.extended.language)
    if request.method != 'POST':
        return JsonResponse({'error': _('Unknown error')})
    if request.user.extended.role != USER_ROLES[2][0]:
        return JsonResponse({'error': _("No access")})
    ClearFiles()
    objects_without_relations(Computer).delete()
    objects_without_relations(Component).delete()
    objects_without_relations(UnknownProblem).delete()
    return JsonResponse({'message': _("All unused files and DB rows were deleted")})


@login_required
@unparallel_group([Job])
def recalculation(request):
    activate(request.user.extended.language)
    if request.method != 'POST':
        return JsonResponse({'error': 'Unknown error'})
    if request.user.extended.role != USER_ROLES[2][0]:
        return JsonResponse({'error': _("No access")})
    if 'type' not in request.POST:
        return JsonResponse({'error': 'Unknown error'})
    res = Recalculation(request.POST['type'], request.POST.get('jobs', None))
    if res.error is not None:
        return JsonResponse({'error': res.error + ''})
    return JsonResponse({'message': _("Caches were successfully recalculated")})


@login_required
def view_call_logs(request):
    activate(request.user.extended.language)
    return render(request, "tools/CallLogs.html", {})


def call_list(request):
    activate(request.user.extended.language)
    if not request.user.is_authenticated or request.method != 'POST' or request.user.extended.role != USER_ROLES[2][0]:
        return HttpResponse('<h1>Unknown error</h1>')
    action = request.POST.get('action')
    if action == 'between':
        date1 = None
        if 'date1' in request.POST:
            date1 = float(request.POST['date1'])
        date2 = None
        if 'date2' in request.POST:
            date2 = float(request.POST['date2'])
        data = ProfileData().get_log(date1, date2)
    elif action == 'around' and 'date' in request.POST:
        if 'interval' in request.POST:
            data = ProfileData().get_log_around(float(request.POST['date']), int(request.POST['interval']))
        else:
            data = ProfileData().get_log_around(float(request.POST['date']))
    else:
        return HttpResponse('<h1>Unknown error</h1>')
    return render(request, "tools/LogList.html", {'data': data})


def call_statistic(request):
    activate(request.user.extended.language)
    if not request.user.is_authenticated or request.method != 'POST' or request.user.extended.role != USER_ROLES[2][0]:
        return HttpResponse('<h1>Unknown error</h1>')
    action = request.POST.get('action')
    data = None
    if action == 'between':
        date1 = None
        if 'date1' in request.POST:
            date1 = float(request.POST['date1'])
        date2 = None
        if 'date2' in request.POST:
            date2 = float(request.POST['date2'])
        data = ProfileData().get_statistic(date1, date2, request.POST.get('name'))
    elif action == 'around' and 'date' in request.POST:
        if 'interval' in request.POST:
            data = ProfileData().get_statistic_around(float(request.POST['date']), int(request.POST['interval']))
        else:
            data = ProfileData().get_statistic_around(float(request.POST['date']))
    return render(request, "tools/CallStatistic.html", {'data': data})
