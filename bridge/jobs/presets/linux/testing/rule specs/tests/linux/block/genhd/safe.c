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
#include <linux/genhd.h>
#include <verifier/nondet.h>

static int __init ldv_init(void)
{
	int minors1 = ldv_undef_int(), minors2 = ldv_undef_int();
	struct gendisk *disk1, *disk2;

	disk1 = alloc_disk(minors1);
	if (!disk1)
		return ldv_undef_int_negative();

	add_disk(disk1);
	del_gendisk(disk1);

	add_disk(disk1);
	del_gendisk(disk1);
	put_disk(disk1);

	disk2 = alloc_disk(minors2);
	if (!disk2)
		return ldv_undef_int_negative();

	add_disk(disk2);
	del_gendisk(disk2);

	add_disk(disk2);
	del_gendisk(disk2);
	put_disk(disk2);

	return 0;
}

module_init(ldv_init);
