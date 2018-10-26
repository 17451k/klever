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
#include <linux/spinlock.h>
#include <linux/gfp.h>
#include "memory.h"

static DEFINE_SPINLOCK(ldv_lock);

static int __init ldv_init(void)
{
	ldv_alloc(GFP_ATOMIC);
	ldv_alloc(GFP_NOWAIT);
	ldv_nonatomic_alloc();

	spin_lock(&ldv_lock);
	ldv_alloc(GFP_ATOMIC);
	ldv_alloc(GFP_NOWAIT);
	spin_unlock(&ldv_lock);

	ldv_nonatomic_alloc();
	ldv_alloc(GFP_ATOMIC);
	ldv_nonatomic_alloc();
	ldv_alloc(GFP_NOIO);
	ldv_nonatomic_alloc();

	if (spin_trylock(&ldv_lock)) {
		ldv_alloc(GFP_ATOMIC);
		ldv_alloc(GFP_NOWAIT);
		spin_unlock(&ldv_lock);
	}

	ldv_nonatomic_alloc();
	ldv_alloc(GFP_NOWAIT);
	ldv_alloc(GFP_ATOMIC);

	return 0;
}

module_init(ldv_init);
