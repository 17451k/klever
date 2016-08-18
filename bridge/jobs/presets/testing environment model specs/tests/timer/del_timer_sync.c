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

#include <linux/module.h>
#include <linux/timer.h>
#include <linux/emg/test_model.h>
#include <verifier/nondet.h>

struct timer_list ldv_timer;
unsigned long expires;

void ldv_handler(unsigned long data)
{
	ldv_invoke_callback();
}

static int __init ldv_init(void)
{
    int flip_a_coin;

	setup_timer(&ldv_timer, ldv_handler, 0);
	flip_a_coin = ldv_undef_int();
    if (flip_a_coin) {
        ldv_register();
        if (!mod_timer(&ldv_timer, jiffies + msecs_to_jiffies(200))) {
            del_timer_sync(&ldv_timer);
            ldv_deregister();
        }
    }
    return 0;
}

static void __exit ldv_exit(void)
{
    /* pass */
}

module_init(ldv_init);
module_exit(ldv_exit);