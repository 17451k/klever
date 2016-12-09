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

#include <linux/types.h>
#include <linux/spi/spi.h>
#include <linux/ldv/device.h>
#include <verifier/memory.h>

struct spi_master *ldv_spi_alloc_master(struct device *host, unsigned size)
{
	struct spi_master *master;

	master = ldv_zalloc(size + sizeof(struct spi_master));

	if (!master)
		return NULL;

    ldv_dev_set_drvdata(&master->dev, &master[1]);

	return master;
}
