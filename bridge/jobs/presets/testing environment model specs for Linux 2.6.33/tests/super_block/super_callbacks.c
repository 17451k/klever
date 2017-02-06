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

#include <linux/module.h>
#include <linux/fs.h>
#include <linux/emg/test_model.h>
#include <verifier/nondet.h>

int flip_a_coin;

void ldv_put(struct super_block *sb)
{
    ldv_release_down();
}

static struct super_operations sops = {
    .put_super = ldv_put,
};

int fill_super(struct super_block *sb, void *a, int b)
{
    sb->s_op = & sops;
	ldv_probe_up();
	return 0;
}

static int ldv_probe(struct file_system_type *fs_type, int flags, const char *dev_name, void *data, struct vfsmount *mnt)
{
	int res;

	ldv_invoke_callback();
	res = get_sb_nodev(& fs_type, flags, NULL, & fill_super, & mnt);
	if (!res)
		ldv_probe_up();
	return res;
}

static void ldv_disconnect(struct super_block *sb)
{
	ldv_release_down();
	ldv_invoke_callback();
}

static struct file_system_type ldv_driver = {
	.get_sb = ldv_probe,
	.kill_sb = ldv_disconnect,
};

static int __init ldv_init(void)
{
	flip_a_coin = ldv_undef_int();
	if (flip_a_coin) {
		ldv_register();
		return register_filesystem(&ldv_driver);
	}
	return 0;
}

static void __exit ldv_exit(void)
{
	if (flip_a_coin) {
		unregister_filesystem(&ldv_driver);
		ldv_deregister();
	}
}

module_init(ldv_init);
module_exit(ldv_exit);
