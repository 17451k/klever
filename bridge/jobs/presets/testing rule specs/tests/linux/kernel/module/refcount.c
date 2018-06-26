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

#include <linux/module.h>
#include <verifier/nondet.h>

static int __init ldv_init(void)
{
	struct module *module1 = ldv_undef_ptr();
	struct module *module2 = ldv_undef_ptr();

	__module_get(module1);
	__module_get(module2);

	if (module_refcount(module1) == 2) {
		module_put(module1);
		module_put(module2);
	}

	return 0;
}

module_init(ldv_init);
