#
# Copyright (c) 2018 ISP RAS (http://www.ispras.ru)
# Ivannikov Institute for System Programming of the Russian Academy of Sciences
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

from django.urls import path
from tools import views


urlpatterns = [
    path('manager/', views.ManagerPageView.as_view(), name='manager'),
    path('call-logs/', views.CallLogsView.as_view(), name='call-logs'),
    path('processing-list/', views.ProcessingListView.as_view(), name='processing-list'),

    path('api/clear-system/', views.ClearSystemAPIView.as_view(), name='api-clear-system'),
    path('api/recalculation/', views.RecalculationAPIView.as_view(), name='api-recalc'),
    path('api/recalculation-marks/', views.MarksRecalculationAPIView.as_view(), name='api-recalc-marks'),
    path('api/call-log/', views.CallLogAPIView.as_view(), name='api-call-log'),
    path('api/call-statistic/', views.CallStatisticAPIView.as_view(), name='api-call-statistic'),
    path('api/clear-call-logs/', views.ClearLogsAPIView.as_view(), name='api-clear-logs'),
    path('api/clear-tasks/', views.ClearTasksAPIView.as_view(), name='api-clear-tasks'),
    path('api/manual-unlock/', views.ManualUnlockAPIView.as_view(), name='api-manual-unlock'),
]
