#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2025 Martin Ottens
# 
# This program is free software: you can redistribute it and/or modify 
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful, 
# but WITHOUT ANY WARRANTY; without even the implied warranty of 
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the 
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License 
# along with this program. If not, see https://www.gnu.org/licenses/.
#

from enum import Enum
from dataclasses import dataclass, field
from typing import List

from utils.settings import TestbedConfig, ApplicationConfig


class ApplicationStatusType(Enum):
    INITIALIZED = "initialized"
    INSTALLATION_FAILED = "install_failed"
    INSTALLED = "installed"
    STARTED = "started"
    FINISHED = "finished"
    FAILED = "failed"

    def __str__(self):
        return str(self.value)
    
    @staticmethod
    def from_str(status: str):
        try: return ApplicationStatusType(status)
        except Exception:
            return ApplicationStatusType.FAILED


@dataclass
class ApplicationStatusReport:
    config: ApplicationConfig
    status: ApplicationStatusType = ApplicationStatusType.INITIALIZED
    stdout: List[str] = field(default_factory=list)
    stderr: List[str] = field(default_factory=list)


class FullResultWrapper:
    def __init__(self, testbed_config: TestbedConfig) -> None:
        self.status_map = {}

        for instance in testbed_config.instances:
            for application in instance.applications:
                key = (instance.name, application.name)
                val = ApplicationStatusReport(config=ApplicationConfig)
                self.status_map[key] = val

    def append_extended_log(self, instance: str, application: str, 
                            message: str, stderr: bool = False) -> bool:
        if (instance, application) not in self.status_map.keys():
            return False
        
        entry: ApplicationStatusReport = self.status_map.get((instance, application))
        if stderr:
            entry.stderr.append(message)
        else:
            entry.stdout.append(message)

        return True
    
    def change_status(self, instance: str, application: str, 
                      new_status: ApplicationStatusType) -> bool:
        if (instance, application) not in self.status_map.keys():
            return False
        
        self.status_map.get((instance, application)).status = new_status
        return True
