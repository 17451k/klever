/*
 * Copyright (c) 2014-2015 ISPRAS (http://www.ispras.ru)
 * Institute for System Programming of the Russian Academy of Sciences
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

#include <linux/cpumask.h>
#include <linux/ldv/common.h>
#include <verifier/common.h>
#include <verifier/nondet.h>

/* MODEL_FUNC_DEF Check offset value and return value between 0 and size. */
unsigned long ldv_find_next_bit(unsigned long size, unsigned long offset)
{
	/* ASSERT Offset should not be greater than size. */
	ldv_assert("linux:bitops::offset out of range", offset <= size);
	/* RETURN Return value between 0 and size. */
	unsigned long nondet = ldv_undef_ulong();
	ldv_assume (nondet <= size);
	ldv_assume (nondet >= 0);
	return nondet;
}

/* MODEL_FUNC_DEF Function returns value between 0 and size. */
unsigned long ldv_find_first_bit(unsigned long size)
{
	/* RETURN Return value between 0 and size. */
	unsigned long nondet = ldv_undef_ulong();
	ldv_assume (nondet <= size);
	ldv_assume (nondet >= 0);
	return nondet;
}

/* MODEL_FUNC_DEF Cut impossible pathes */
void ldv_initialize(void)
{
	ldv_assume(nr_cpu_ids > 0);
}
