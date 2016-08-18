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

#include <linux/ldv/common.h>
#include <verifier/common.h>
#include <verifier/nondet.h>

int ldv_sysfs = 0;

/* MODEL_FUNC_DEF Create sysfs group. */
int ldv_sysfs_create_group(void)
{
	/* OTHER Choose an arbitrary return value. */
	int res = ldv_undef_int_nonpositive();
	/* OTHER If memory is not available. */
	if (!res) {
		/* CHANGE_STATE Increase allocated counter. */
		ldv_sysfs++;
		/* RETURN Sysfs group was successfully created. */
		return 0;
	}
	/* RETURN There was an error during sysfs group creation. */
	return res;
}

/* MODEL_FUNC_DEF Remove sysfs group. */
void ldv_sysfs_remove_group(void)
{
	/* ASSERT Sysfs group must be allocated before. */
	ldv_assert("linux:sysfs::less initial decrement", ldv_sysfs >= 1);
	/* CHANGE_STATE Decrease allocated counter. */
	ldv_sysfs--;
}

/* MODEL_FUNC_DEF Check that all sysfs groups are not incremented at the end */
void ldv_check_final_state( void )
{
	/* ASSERT Sysfs groups must be freed at the end. */
	ldv_assert("linux:sysfs::more initial at exit", ldv_sysfs == 0);
}
