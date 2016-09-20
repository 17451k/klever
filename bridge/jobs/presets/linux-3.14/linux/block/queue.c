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

struct request_queue;

enum {
/* There are 2 possible states of queue. */
  LDV_NO_QUEUE = 0,     /* There is no queue or queue was cleaned. */
  LDV_INITIALIZED_QUEUE /* Queue was created. */
};

static int ldv_queue_state = LDV_NO_QUEUE;

/* MODEL_FUNC_DEF Allocate queue. */
struct request_queue *ldv_request_queue(void)
{
	/* ASSERT Queue should not be allocated twice. */
	ldv_assert("linux:block:queue::double allocation", ldv_queue_state == LDV_NO_QUEUE);
	/* OTHER Choose an arbitrary return value. */
	struct request_queue *res = (struct request_queue *)ldv_undef_ptr();
	/* OTHER If memory is not available. */
	if (res) {
		/* CHANGE_STATE Allocate gendisk. */
		ldv_queue_state = LDV_INITIALIZED_QUEUE;
		/* RETURN Queue was successfully created. */
		return res;
	}
	/* RETURN There was an error during queue creation. */
	return res;
}

/* MODEL_FUNC_DEF Free queue. */
void ldv_blk_cleanup_queue(void)
{
	/* ASSERT Queue should be allocated . */
	ldv_assert("linux:block:queue::use before allocation", ldv_queue_state == LDV_INITIALIZED_QUEUE);
	/* CHANGE_STATE Free queue. */
	ldv_queue_state = LDV_NO_QUEUE;
}

/* MODEL_FUNC_DEF Check that queue are not allocated at the end */
void ldv_check_final_state(void)
{
	/* ASSERT Queue must be freed at the end. */
	ldv_assert("linux:block:queue::more initial at exit", ldv_queue_state == LDV_NO_QUEUE);
}
