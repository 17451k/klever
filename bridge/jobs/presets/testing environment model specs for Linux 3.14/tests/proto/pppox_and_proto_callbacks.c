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
#include <linux/if_pppox.h>
#include <linux/emg/test_model.h>
#include <verifier/nondet.h>

int flip_a_coin;

int ldv_create(struct net *net, struct socket *sock)
{
	ldv_probe_up();
	return 0;
}

int ldv_release(struct socket *sock)
{
    ldv_release_down();
}

int ldv_bind(struct socket *sock, struct sockaddr *myaddr, int sockaddr_len)
{
    ldv_probe_up();
    return 0;
}

const struct pppox_proto ldv_driver = {
	.create = ldv_create
};

struct proto_ops ldv_proto_ops = {
    .bind = ldv_bind,
    .release = ldv_release
};

static int __init ldv_init(void)
{
	flip_a_coin = ldv_undef_int();
	if (flip_a_coin) {
		ldv_register();
		return register_pppox_proto(5, & ldv_driver);
	}
	return 0;
}

static void __exit ldv_exit(void)
{
	if (flip_a_coin) {
	    ldv_release_completely();
		unregister_pppox_proto(5);
		ldv_deregister();
	}
}

module_init(ldv_init);
module_exit(ldv_exit);
