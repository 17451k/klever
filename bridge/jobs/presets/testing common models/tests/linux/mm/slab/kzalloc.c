/*
 * Copyright (c) 2017 ISPRAS (http://www.ispras.ru)
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
#include <linux/slab.h>
#include <linux/ldv/slab.h>
#include <ldv-test.h>
#include <verifier/common.h>
#include <verifier/nondet.h>

gfp_t ldv_flags;
bool ldv_is_flags_equal = false;
void *ldv_res;

void ldv_check_alloc_flags(gfp_t flags)
{
	if (flags == ldv_flags)
		ldv_is_flags_equal = true;
}

void ldv_after_alloc(void *res)
{
	ldv_res = res;
}

static int __init ldv_init(void)
{
	size_t size = ldv_undef_uint();

	ldv_flags = ldv_undef_uint();
	if (kzalloc(size, ldv_flags) == ldv_res && ldv_is_flags_equal)
		ldv_error();

	return 0;
}

module_init(ldv_init);
