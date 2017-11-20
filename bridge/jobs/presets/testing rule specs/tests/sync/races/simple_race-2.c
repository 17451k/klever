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

/*
 * A simple test with races, repeated functions and recursion
 */

#include <linux/module.h>
#include <linux/mutex.h>
#include <verifier/nondet.h>
#include <verifier/thread.h>

static DEFINE_MUTEX(ldv_lock);
static int _ldv_global_var;

static void *ldv_func2(void *arg);

void ldv_recursive_func(void) {
	if (ldv_undef_int()) {
		ldv_func2(&_ldv_global_var);
	} else {
		_ldv_global_var = 1;
	}
}

static void *ldv_func2(void *arg) {
	ldv_recursive_func();
}

static void *ldv_func1(void *arg) {
	ldv_func2(&_ldv_global_var);
	_ldv_global_var = 2;
	mutex_lock(&ldv_lock);
	_ldv_global_var = 3;
	ldv_func2(&_ldv_global_var);
	_ldv_global_var = 4;
	mutex_unlock(&ldv_lock);
	_ldv_global_var = 5;
}

static int __init init(void)
{
	pthread_t thread1, thread2;
	pthread_attr_t const *attr1 = ldv_undef_ptr(), *attr2 = ldv_undef_ptr();
	void *arg1 = ldv_undef_ptr(), *arg2 = ldv_undef_ptr();

	pthread_create(&thread1, attr1, &ldv_func1, arg1);
	pthread_create(&thread2, attr2, &ldv_func2, arg2);

	return 0;
}

module_init(init);
