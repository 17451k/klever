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

#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/usb.h>


static int ldv_usb_probe(struct usb_interface *interface,
                         const struct usb_device_id *id)
{
	int err;
	struct usb_driver *ldv_usb_driver2;

	err = usb_register(ldv_usb_driver2);

	return 0;
}

static struct usb_driver ldv_usb_driver = {
	.probe = ldv_usb_probe
};

static int __init init(void)
{
	return usb_register(&ldv_usb_driver);
}

module_init(init);
