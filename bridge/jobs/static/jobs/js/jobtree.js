/*
 * Copyright (c) 2014-2016 ISPRAS (http://www.ispras.ru)
 * Institute for System Programming of the Russian Academy of Sciences
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * ee the License for the specific language governing permissions and
 * limitations under the License.
 */

var do_not_count = [
    'name', 'author', 'date', 'status', '', 'resource', 'format', 'version', 'type', 'identifier',
    'parent_id', 'role', 'priority', 'start_date', 'finish_date', 'solution_wall_time', 'operator',
    'tasks:start_ts', 'tasks:finish_ts', 'tasks:progress_ts', 'tasks:expected_time_ts',
    'subjobs:start_sj', 'subjobs:finish_sj', 'subjobs:progress_sj', 'subjobs:expected_time_sj'
];

function fill_all_values() {
    $("td[id^='all__']").each(function() {
        var cell_id_data = $(this).attr('id').split('__');
        if ($.inArray(cell_id_data.slice(1, -1).join(':'), do_not_count) === -1) {
            cell_id_data[0] = 'value';
            var sum = 0, have_numbers = false;
            $("td[id^='" + cell_id_data.join('__') + "__']").each(function () {
                var num = parseInt($(this).children().first().text());
                isNaN(num) ? num = 0 : have_numbers = true;
                sum += num;
            });
            if (have_numbers) {
                $(this).text(sum);
            }
        }
    });
}

function fill_checked_values() {
    $("td[id^='checked__']").each(function() {
        var cell_id_data = $(this).attr('id').split('__');
        if ($.inArray(cell_id_data[1], do_not_count) === -1) {
            cell_id_data[0] = 'value';
            var sum = 0, have_numbers = false, is_checked = false;
            $("td[id^='" + cell_id_data.join('__') + "__']").each(function() {
                if ($('#job_checkbox__' + $(this).attr('id').split('__').slice(-1)[0]).is(':checked')) {
                    is_checked = true;
                    var num = parseInt($(this).children().first().text());
                    isNaN(num) ? num = 0 : have_numbers = true;
                    sum += num;
                }
            });
            (have_numbers === true && is_checked === true) ? $(this).text(sum) : $(this).text('-');
        }
    });
}

function check_jobs_access(jobs) {
    var status = true;
    $.ajax({
        url: job_ajax_url + 'check_access/',
        type: 'POST',
        dataType: 'json',
        data: {jobs: JSON.stringify(jobs)},
        async: false,
        success: function (res) {
            if (res.error) {
                err_notify(res.message);
                status = false;
            }
        }
    });
    return status;
}

function compare_jobs() {
    var selected_jobs = [];
    $('input[id^="job_checkbox__"]:checked').each(function () {
        selected_jobs.push($(this).attr('id').replace('job_checkbox__', ''));
    });
    if (selected_jobs.length !== 2) {
        err_notify($('#error__no_jobs_to_compare').text());
        return false;
    }
    $('#dimmer_of_page').addClass('active');
    $.post(
        job_ajax_url + 'check_compare_access/',
        {
            job1: selected_jobs[0],
            job2: selected_jobs[1]
        },
        function (data) {
            if (data.error) {
                $('#dimmer_of_page').removeClass('active');
                err_notify(data.error);
            }
            else {
                $.post(
                    '/reports/ajax/fill_compare_cache/',
                    {
                        job1: selected_jobs[0],
                        job2: selected_jobs[1]
                    },
                    function (data) {
                        $('#dimmer_of_page').removeClass('active');
                        if (data.error) {
                            err_notify(data.error);
                        }
                        else {
                            window.location.href = '/reports/comparison/' + selected_jobs[0] + '/' + selected_jobs[1] + '/';
                        }
                    },
                    'json'
                );
            }
        },
        'json'
    );
}

$(document).ready(function () {
    $('.ui.dropdown').dropdown();

    $('#remove_jobs_popup').modal({transition: 'fly up', autofocus: false, closable: false});
    $('#show_remove_jobs_popup').click(function () {
        $('#jobs_actions_menu').popup('hide');
        var jobs_for_delete = [], confirm_delete_btn = $('#delete_jobs_btn'),
            confirm_delete_modal = $('#remove_jobs_popup');
        $("input[id^='job_checkbox__']").each(function () {
            if ($(this).is(':checked')) {
                jobs_for_delete.push($(this).attr('id').replace('job_checkbox__', ''));
            }
        });
        if (!jobs_for_delete.length) {
            err_notify($('#error__no_jobs_to_delete').text());
            confirm_delete_modal.modal('hide');
        }
        else {
            confirm_delete_modal.modal('show');
            confirm_delete_btn.unbind();
            confirm_delete_btn.click(function () {
                confirm_delete_modal.modal('hide');
                $('#dimmer_of_page').addClass('active');
                $.post(
                    job_ajax_url + 'removejobs/',
                    {jobs: JSON.stringify(jobs_for_delete)},
                    function (data) {
                        $('#dimmer_of_page').removeClass('active');
                        data.error ? err_notify(data.error) : window.location.replace('');
                    },
                    'json'
                );
            });
        }
    });

    inittree($('.tree'), 2, 'chevron down violet icon', 'chevron right violet icon');
    fill_all_values();
    $("input[id^='job_checkbox__']").change(fill_checked_values);

    $('#cancel_remove_jobs').click(function () {
        $('#remove_jobs_popup').modal('hide');
    });

    $('#download_selected_jobs').click(function (event) {
        event.preventDefault();

        $('#jobs_actions_menu').popup('hide');
        var job_ids = [];
        $('input[id^="job_checkbox__"]:checked').each(function () {
            job_ids.push($(this).attr('id').replace('job_checkbox__', ''));
        });
        if (job_ids.length) {
            if (check_jobs_access(job_ids)) {
                $.redirectPost(job_ajax_url + 'downloadjobs/', {job_ids: JSON.stringify(job_ids)});
            }
        }
        else {
            err_notify($('#error__no_jobs_to_download').text());
        }
    });

    $('#compare_reports_btn').click(compare_jobs);
});
