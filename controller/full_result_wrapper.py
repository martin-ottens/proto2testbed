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

import sys

from loguru import logger
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional, Any
from datetime import datetime

from utils.settings import TestbedConfig, ApplicationConfig, TestbedInstance
from common.instance_manager_message import LogMessageType, ApplicationStatus
from state_manager import AgentManagementState


@dataclass
class LogEntry:
    time: datetime
    type: LogMessageType
    message: str


@dataclass
class ApplicationStatusReport:
    config: ApplicationConfig
    status: ApplicationStatus = ApplicationStatus.PENDING
    logs: List[LogEntry] = field(default_factory=list)
    data_series: List[Any] = field(default_factory=list)


@dataclass
class InstanceStatusReport:
    config: TestbedInstance
    logs: List[LogEntry] = field(default_factory=list)
    status: AgentManagementState = AgentManagementState.UNKNOWN
    preserve: Optional[Tuple[str, int]] = None


class FullResultWrapper:
    def __init__(self, testbed_config: TestbedConfig) -> None:
        self.application_status_map: Dict[Tuple[str, str], ApplicationStatusReport] = {}
        self.instance_status_map: Dict[str, InstanceStatusReport] = {}
        self.controller_log: List[LogEntry] = []
        self.controller_failed: bool = False
        self.experiment_tag: Optional[str] = None

        for instance in testbed_config.instances:
            self.instance_status_map[instance.name] = InstanceStatusReport(config=instance)
            for application in instance.applications:
                key = (instance.name, application.name)
                val = ApplicationStatusReport(config=application)
                self.application_status_map[key] = val

    def append_application_log(self, instance: str, application: str, 
                               message: str, type: LogMessageType) -> bool:
        if (instance, application) not in self.application_status_map.keys():
            logger.warning(f"ResultWrapper: Unable to find application {application}@{instance}")
            return False
        
        if type == LogMessageType.NONE:
            return True
        
        entry: ApplicationStatusReport = self.application_status_map.get((instance, application))
        entry.logs.append(LogEntry(time=datetime.now(), type=type, message=message))

        return True
    
    def append_controller_log(self, message: str, level: str, time: datetime) -> None:
        matched_level = LogMessageType.NONE
        match (level):
            case "INFO":
                matched_level = LogMessageType.MSG_INFO
            case "DEBUG":
                matched_level = LogMessageType.MSG_DEBUG
            case "SUCCESS":
                matched_level = LogMessageType.MSG_SUCCESS
            case "WARNING":
                matched_level = LogMessageType.MSG_WARNING
            case "ERROR" | "CRITICAL":
                matched_level = LogMessageType.MSG_ERROR
        
        if matched_level == LogMessageType.NONE:
            return
        
        self.controller_log.append(LogEntry(message=message, type=matched_level, time=time))
    
    def change_application_status(self, instance: str, application: str, 
                      new_status: ApplicationStatus) -> bool:
        if (instance, application) not in self.application_status_map.keys():
            return False
        
        self.application_status_map.get((instance, application)).status = new_status
        return True
    
    def change_instance_status(self, instance: str, new_status: AgentManagementState) -> bool:
        if instance not in self.instance_status_map.keys():
            return False
        
        self.instance_status_map.get(instance).status = new_status
        return True
    
    def append_instance_log(self, instance: str, message: str, type: LogMessageType) -> bool:
        if instance not in self.instance_status_map.keys():
            logger.warning(f"ResultWrapper: Unable to find instance {instance}")
            return False
        
        if type == LogMessageType.NONE:
            return True

        entry = LogEntry(time=datetime.now(), type=type, message=message)
        self.instance_status_map[instance].logs.append(entry)
        return True
    
    def add_instance_preserved_files(self, instance: str, target: str, amount: int) -> bool:
        if instance not in self.instance_status_map.keys():
            return False
        
        self.instance_status_map.get(instance).preserve = (target, amount)
        return True
    
    def add_data_point(self, point: Dict) -> bool:
        tags = point.get("tags", None)
        if tags is None:
            return False

        instance = tags.get("instance", None)
        application = tags.get("application", None)

        if (instance, application) not in self.application_status_map.keys():
            return False
        
        self.application_status_map.get((instance, application)).data_series.append(point)
        return True
    
    def dump_state(self, file=sys.stdout) -> None:
        print(f"### BEGIN DUMP Experiment: {self.experiment_tag}, success={self.controller_failed}", file=file)

        print("APPLICATIONS \n", file=file)
        for tup, application in self.application_status_map.items():
            instance, name = tup
            print(f"----- {name}@{instance}: {application.status}", file=file)
            print("Logs:", file=file)
            for log in application.logs:
                print(f"{log.time.isoformat()} - {log.type.prefix} {log.message}", file=file)

            print("Datapoints:", file=file)
            for entry in application.data_series:
                print(f"{entry}", file=file)

        print("\nINSTANCES\n", file=file)
        for name, instance in self.instance_status_map.items():
            print(f"----- {name}: {instance.status}", file=file)

            if instance.preserve is not None:
                print(f"Preserved {instance.preserve[1]} files to {instance.preserve[0]}", file=file)

            print("Logs:", file=file)
            for log in instance.logs:
                print(f"{log.time.isoformat()} - {log.type.prefix} {log.message}", file=file)

        print("\nCONTROLLER LOG\n", file=file)
        for log in self.controller_log:
            print(f"{log.time.isoformat()} - {log.type.prefix} {log.message}", file=file)

        print(f"### END DUMP Experiment: {self.experiment_tag}, success={self.controller_failed}", file=file)
