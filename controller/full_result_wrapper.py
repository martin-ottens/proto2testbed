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
from typing import List, Tuple, Dict
from datetime import datetime

from utils.settings import TestbedConfig, ApplicationConfig
from common.instance_manager_message import LogMessageType


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
class LogEntry:
    time: int
    message: str


@dataclass
class ApplicationStatusReport:
    config: ApplicationConfig
    status: ApplicationStatusType = ApplicationStatusType.INITIALIZED
    logs: List[LogEntry] = field(default_factory=list)


class FullResultWrapper:
    def __init__(self, testbed_config: TestbedConfig) -> None:
        self.application_status_map: Dict[Tuple[str, str], ApplicationStatusReport] = {}
        self.instance_log_map: Dict[str, List[LogEntry]] = {}

        for instance in testbed_config.instances:
            self.instance_log_map[instance.name] = []
            for application in instance.applications:
                key = (instance.name, application.name)
                val = ApplicationStatusReport(config=ApplicationConfig)
                self.application_status_map[key] = val

    def append_extended_log(self, instance: str, application: str, 
                            message: str, type: LogMessageType) -> bool:
        if (instance, application) not in self.application_status_map.keys():
            return False
        
        if type == LogMessageType.NONE:
            return True
        
        entry: ApplicationStatusReport = self.application_status_map.get((instance, application))
        entry.logs.append(LogEntry(time=datetime.now(), message=f"{type.prefix}{message}"))

        return True
    
    def change_status(self, instance: str, application: str, 
                      new_status: ApplicationStatusType) -> bool:
        if (instance, application) not in self.application_status_map.keys():
            return False
        
        self.application_status_map.get((instance, application)).status = new_status
        return True
    
    def append_instance_log(self, instance: str, message: str, type: LogMessageType) -> bool:
        if instance not in self.instance_log_map.keys():
            return False
        
        if type == LogMessageType.NONE:
            return True

        entry = LogEntry(time=datetime.now(), message=f"{type.prefix}{message}")
        self.instance_log_map[instance].append(entry)
        return True
