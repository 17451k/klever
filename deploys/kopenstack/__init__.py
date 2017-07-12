#
# Copyright (c) 2017 ISPRAS (http://www.ispras.ru)
# Institute for System Programming of the Russian Academy of Sciences
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import argparse
import getpass
import logging
import os
import sys

from kopenstack.kopenstack import execute_os_entity_action


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['show', 'create', 'update', 'ssh', 'remove'], help='Action to be executed.')
    parser.add_argument('entity',
                        choices=['Klever base image', 'Klever developer instance', 'Klever experimental instances'],
                        help='Entity for which action to be executed.')
    parser.add_argument('--os-auth-url', default='https://cloud.ispras.ru:5000/v2.0',
                        help='OpenStack identity service endpoint for authorization (default: "%(default)s").')
    parser.add_argument('--os-username', default=getpass.getuser(),
                        help='OpenStack username for authentication (default: "%(default)s").')
    parser.add_argument('--os-tenant-name', default='computations',
                        help='OpenStack tenant name (default: "%(default)s").')
    parser.add_argument('--ssh-username', default='debian',
                        help='SSH username for authentication (default: "%(default)s").')
    parser.add_argument('--ssh-rsa-private-key-file',
                        help='Path to SSH RSA private key file.'
                             'The appropriate SSH RSA key pair should be stored to OpenStack by name "ldv"')
    parser.add_argument('--name', help='Entity name.')
    parser.add_argument('--base-image', default='Debian 9.0.4 64-bit',
                        help='Name of base image on which Klever base image will be based on (default: "%(default)s").')
    parser.add_argument('--klever-base-image', default='Klever Base',
                        help='Name of Klever base image on which instances will be based on (default: "%(default)s").')
    parser.add_argument('--flavor', default='spark.large',
                        help='Name of flavor to be used for new instances (default: "%(default)s").')
    parser.add_argument('--volume-size', type=int,
                        help='Size of volume in GB to be attached to new instances.')
    parser.add_argument('--klever-configuration-file', default=os.path.join(os.path.dirname(__file__), os.path.pardir,
                                                                            'conf', 'klever.json'),
                        help='Path to Klever configuration file (default: "%(default)s").')
    args = parser.parse_args()

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s (%(filename)s:%(lineno)03d) %(levelname)s> %(message)s', "%Y-%m-%d %H:%M:%S")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    execute_os_entity_action(args, logger)
