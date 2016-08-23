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
#include <scsi/scsi_dh.h>
#include <linux/emg/test_model.h>
#include <verifier/nondet.h>

static int ldv_attach(struct scsi_device *sdev)
{
	ldv_invoke_reached();
	return 0;
}

static void ldv_detach(struct scsi_device *sdev)
{
	ldv_invoke_reached();
}

static struct scsi_device_handler ldv_test_struct = {
	.attach = ldv_attach,
	.detach = ldv_detach,
};

static int __init test_init(void)
{
	return scsi_register_device_handler(&ldv_test_struct);
}

static void __exit test_exit(void)
{
	scsi_unregister_device_handler(&ldv_test_struct);
}

module_init(test_init);
module_exit(test_exit);
