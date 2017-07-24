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
import importlib
import core.vtgvrp.vtg.plugins


class FVTP(core.vtgvrp.vtg.plugins.Plugin):

    def __init__(self, conf, logger, parent_id, callbacks, mqs, locks, id=None, work_dir=None, attrs=None,
                 unknown_attrs=None, separate_from_parent=False, include_child_resources=False):
        super(FVTP, self).__init__(conf, logger, parent_id, callbacks, mqs, locks, id, work_dir, attrs,
                                   unknown_attrs, separate_from_parent, include_child_resources)

    def final_task_preparation(self):
        if 'strategy' in self.conf:
            strategy_name = self.conf['strategy']
        else:
            strategy_name = 'basic'

        self.logger.info("Going to use strategy {!r} to generate verification tasks".format(strategy_name))
        try:
            strategy = getattr(importlib.import_module('.{0}'.format(strategy_name.lower()), 'core.vtg.fvtp'),
                               strategy_name.upper())
        except ImportError:
            raise ValueError("There is no strategy {!r}".format(strategy_name))

        self.logger.info('Initialize strategy {!r}'.format(strategy_name))
        s = strategy(self.logger, self.conf, self.abstract_task_desc)

        self.logger.info('Begin task generating')
        for task in s.verification_tasks:
            self._submit_verification_task(task)

    main = final_task_preparation

    def _submit_verification_task(self, verification_task):
        raise NotImplementedError
