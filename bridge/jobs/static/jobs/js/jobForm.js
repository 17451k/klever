/*
 * Copyright (c) 2018 ISP RAS (http://www.ispras.ru)
 * Ivannikov Institute for System Programming of the Russian Academy of Sciences
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


function JobForm(job_id, action) {
    this.save_url = '/jobs/api/save-job/{0}/'.format(job_id);
    this.method = (action === 'copy') ? 'POST' : 'PUT';

    this.labels = {};
    this.inputs = {};
    return this;
}

JobForm.prototype.initialize = function(inputs, labels) {
    var instance = this;
    $.each(inputs, function (key, value) { instance.inputs[key] = value });
    $.each(labels, function (key, value) { instance.labels[key] = value });
};

JobForm.prototype.serialize = function() {
    var instance = this, data = {};
    $.each(instance.inputs, function (key, value) { data[key] = $('#' + value).val() });
    return data;
};

JobForm.prototype.save = function (extra_data) {
    var instance = this, data = this.serialize();
    if (extra_data) $.each(extra_data, function (key, value) { data[key] = value });

    $.ajax({
        url: instance.save_url, type: instance.method, data: JSON.stringify(data),
        processData: false, dataType: "json", contentType: "application/json",
        success: function (resp) {
            $('#dimmer_of_page').removeClass('active');
            resp.error ? err_notify(resp.error) : window.location.replace(resp['url']);
        },
        error: function (resp) {
            $('#dimmer_of_page').removeClass('active');
            var errors = flatten_api_errors(resp['responseJSON'], instance.labels);
            $.each(errors, function (i, err_text) { err_notify(err_text, 3000) });
        }
    });
};
