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

#include <linux/module.h>
#include <verifier/nondet.h>

static int __init ldv_init(void)
{
	struct module *module1 = ldv_undef_ptr();
	struct module *module2 = ldv_undef_ptr();

	if (try_module_get(module1)) {
		if (try_module_get(module2))
			module_put(module2);

		module_put(module1);
	}

	__module_get(module1);
	module_put(module1);

	if (module2 != NULL) {
		__module_get(module2);
		__module_get(module2);
		module_put_and_exit(0);
		module_put(module2);
		module_put(module2);
		module_put(module2);
	}

	if (module1 != NULL) {
		__module_get(module1);
		__module_get(module1);

		if (module_refcount(module1) == 2) {
			module_put(module1);
			module_put(module1);
		}
	}

	return 0;
}

module_init(ldv_init);
