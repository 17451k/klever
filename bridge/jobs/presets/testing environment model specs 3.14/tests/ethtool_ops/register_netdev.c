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
#include <linux/netdevice.h>
#include <linux/emg/test_model.h>
#include <verifier/nondet.h>

struct net_device dev;
int flip_a_coin;

static int set_settings(struct net_device *dev, struct ethtool_cmd *cmd)
{
    ldv_invoke_callback();
    return 0;
}

static struct ethtool_ops ops = {
    .set_settings = set_settings
};

static int __init ldv_init(void)
{
    flip_a_coin = ldv_undef_int();
    if (flip_a_coin) {
        SET_ETHTOOL_OPS(&dev, &ops);
        ldv_register();
        return register_netdev(&dev);
    }
    return 0;
}

static void __exit ldv_exit(void)
{
    if (flip_a_coin) {
        unregister_netdev(&dev);
        ldv_deregister();
    }
}

module_init(ldv_init);
module_exit(ldv_exit);
