# Copyright (c) 2020 ISP RAS (http://www.ispras.ru)
# Ivannikov Institute for System Programming of the Russian Academy of Sciences
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

import os
import setuptools


def package_files(package_directory):
    paths = []

    for (root, _, filenames) in os.walk(package_directory):
        for filename in filenames:
            path = os.path.relpath(
                os.path.join(root, filename), start=package_directory
            )

            paths.append(path)

    return paths


setuptools.setup(
    name="klever",
    use_scm_version={'fallback_version': '3.0'},
    author="ISP RAS",
    author_email="ldv-project@linuxtesting.org",
    url="http://forge.ispras.ru/projects/klever",
    license="LICENSE",
    description="Klever is a software verification framework",
    long_description=open("README", encoding="utf8").read(),
    python_requires=">=3.7",
    packages=["klever"],
    package_data={"klever": package_files("klever")},
    entry_points={
        "console_scripts": [
            "klever-core=klever.core.__main__:main",
            "klever-client-controller=klever.scheduler.main:client_controller",
            "klever-debug-scheduler=klever.scheduler.main:debug_scheduler",
            "klever-native-scheduler=klever.scheduler.main:native_scheduler",
            "klever-scheduler-client=klever.scheduler.main:scheduler_client",
            "klever-verifiercloud-scheduler=klever.scheduler.main:verifiercloud_scheduler",
            "klever-node-check=klever.scheduler.controller.checks.node:main",
            "klever-resources-check=klever.scheduler.controller.checks.resources:main",
            "klever-schedulers-check=klever.scheduler.controller.checks.schedulers:main",
            "klever-build=klever.cli.klever_build:klever_build",
            "klever-download-job=klever.cli.cli:download_job",
            "klever-download-marks=klever.cli.cli:download_marks",
            "klever-download-progress=klever.cli.cli:download_progress",
            "klever-download-results=klever.cli.cli:download_results",
            "klever-start-preset-solution=klever.cli.cli:start_preset_solution",
            "klever-start-solution=klever.cli.cli:start_solution",
            "klever-update-preset-mark=klever.cli.cli:update_preset_mark",
            "klever-update-job=klever.cli.cli:upload_job",
            "klever-deploy-local=klever.deploys.local:main",
            "klever-deploy-openstack=klever.deploys.openstack:main",
        ]
    },
    install_requires=open("requirements.txt", encoding="utf8").read().splitlines(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: Implementation :: CPython",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: POSIX :: Linux",
    ],
)
