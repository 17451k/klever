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

/* Test should check, how the value analysis handles loops. */
#include <linux/module.h>
#include <verifier/nondet.h>
#include <verifier/thread.h>

static int _ldv_global_var;

static int ldv_func1(int a)
{
	return a + 1;
}

static int ldv_func2(void)
{
	int i = 0;
	int res = 0;

	for (i = 0; i < 10000; i++)
		res = ldv_func1(res);

	if (res < 10000)
		_ldv_global_var = 0;

	return 0;
}

static void *ldv_main(void *arg)
{
	_ldv_global_var = 1;
	ldv_func2();

	return NULL;
}

static int __init init(void)
{
	pthread_t thread;
	pthread_attr_t const *attr = ldv_undef_ptr();
	void *arg = ldv_undef_ptr();

	pthread_create(&thread, attr, &ldv_main, arg);
	ldv_main(0);

	return 0;
}

module_init(init);
