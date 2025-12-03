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
from pathlib import Path

from utils.settings import TestbedConfig, ApplicationConfig, TestbedInstance
from common.instance_manager_message import LogMessageType, ApplicationStatus
from state_manager import AgentManagementState


@dataclass
class LogEntry:
    """
    Class representing a single log entry.

    Attributes:
        time (datetime): Log entry time of the host
        type (LogMessageType): Type of the log entry, e.g., stdout
        message (str): Log message
        bool (bool): Indicates if the log entry was added after a snapshot
                     was taken
    """
    time: datetime
    type: LogMessageType
    message: str
    after_snapshot: bool = False


@dataclass
class ApplicationStatusReport:
    """
    Class containing the status of a single Application from an Instance.

    Attributes:
        config (ApplicationConfig): Config of the associated Application
        status (ApplicationStatus): Last observed status of the Application
        logs (List[LogEntry]): List of LogEntry objects
        data_series (List[Any]): Contains the stored time series data from
                                 the Application whenever the data is not
                                 stored in the InfluxDB
    """
    config: ApplicationConfig
    status: ApplicationStatus = ApplicationStatus.PENDING
    logs: List[LogEntry] = field(default_factory=list)
    data_series: List[Any] = field(default_factory=list)


@dataclass
class InstanceStatusReport:
    """
    Class containing the status of a single Instance.

    Attributes:
        config (TestbedInstance): Config of the associated Instance
        logs (List[LogEntry]): List of LogEntry objects
        status (AgentManagementState): Last observed status of the Instance
        preserve (Tuple[str, int] | None): Output base path of preserved files
                               and number of files copied during file preservation.
                               None if file preservation was disabled.
    """
    config: TestbedInstance
    logs: List[LogEntry] = field(default_factory=list)
    status: AgentManagementState = AgentManagementState.UNKNOWN
    preserve: Optional[Tuple[str, int]] = None


class FullResultWrapper:
    """
    Class containing the status of a full testbed execution. The state diffs 
    stored after a checkpoint can be deleted for checkpoint operation.

    Attributes:
        _applicatiation_status_map: Internal use, access via get_application_logs
        _instance_status_map: Internal use, access via get_instance_logs
        _controller_log: Internal use, access via get_controller_logs
        _is_after_snapshot: Internal use, marks if testbed has passed the checkpoint
                            in unwrap_after_init.

        controller_failed (bool): Indicates if an error occurred during generic
                            (experiment independet) setup functions in the 
                            controller, e.g., failure during infrastructure 
                            setup or checkpoint creation. Logs will provide 
                            more detailed information.
        integration_failed (bool): Indicates if an Integration failed. Logs 
                            will provide more detailed information.
        configuration_failed (bool): Indicates if a configuration error occurred:
                            Testbed Config error, Instance setup script error,
                            Application installation error. Logs will provide
                            more detailed information.
        testbed_succeeded (bool): Indicates if the testbed run was successful
        experiment_tag (str | None): Experiment tag of the testbed run, could
                            be None if the FullResultWrapper is accessed before
                            an experiment was started (e.g., due to testbed
                            error)
        testbed_package_path (Path): Path to the Testbed Package directory
                            used in the testbed run.
        testbed_config (TestbedConfig): Deep copy of the TestbedConfig object
                            used in the testbed run.

    """

    def __init__(self, testbed_config: TestbedConfig, testbed_package_path: Path) -> None:
        """
        Creates a new FullResultWrapper object with initial (pre-checkpoint)
        state, must be done before the testbed is started.

        Args:
            testbed_config (TestbedConfig): Deep copy of the TestbedConfig object
                                     used in the testbed run.
            testbed_package_path (Path): Path to the Testbed Package directory
                                     used in the testbed run.
        """
        self._application_status_map: Dict[Tuple[str, str], ApplicationStatusReport] = {}
        self._instance_status_map: Dict[str, InstanceStatusReport] = {}
        self._controller_log: List[LogEntry] = []
        self._is_after_snapshot: bool = False

        self.controller_failed: bool = False
        self.integration_failed: bool = False
        self.configuration_failed: bool = False
        self.testbed_succeeded: bool = False
        self.experiment_tag: Optional[str] = None
        self.testbed_package_path: Path = testbed_package_path
        self.testbed_config: TestbedConfig = testbed_config

        for instance in testbed_config.instances:
            self._instance_status_map[instance.name] = InstanceStatusReport(config=instance)

    def unwrap_after_init(self, testbed_config: TestbedConfig, experiment_tag: str, 
                          testbed_package_path: Path) -> None:
        """
        Internal use only.
        Reset state to checkpoint or marks the beginning of a checkpoint when
        the method was not called before.
        """
        self._is_after_snapshot = True
        self.experiment_tag = experiment_tag
        self.controller_failed = False
        self.integration_failed = False
        self.configuration_failed = False
        self.testbed_succeeded = False
        self.testbed_config = testbed_config
        self.testbed_package_path = testbed_package_path

        self._application_status_map.clear()
        for instance in testbed_config.instances:
            for application in instance.applications:
                key = (instance.name, application.name)
                val = ApplicationStatusReport(config=application)
                self._application_status_map[key] = val

        for instance_report in self._instance_status_map.values():
            instance_report.logs = list(filter(lambda x: not x.after_snapshot, instance_report.logs))
            instance_report.preserve = None
            instance_report.status = AgentManagementState.UNKNOWN

        self._controller_log = list(filter(lambda x: not x.after_snapshot, self._controller_log))

    def append_application_log(self, instance: str, application: str, 
                               message: str, type: LogMessageType) -> bool:
        """
        Internal use only.
        Append LogEntry to a logs list of an ApplicationStatusReport object.
        """
        if (instance, application) not in self._application_status_map.keys():
            raise ValueError(f"FullResultWrapper: Unable to find application {application}@{instance}")
        
        if type == LogMessageType.NONE:
            return True
        
        entry: ApplicationStatusReport = self._application_status_map.get((instance, application))
        entry.logs.append(LogEntry(time=datetime.now(), 
                                   type=type, 
                                   message=message, 
                                   after_snapshot=self._is_after_snapshot))

        return True
    
    def append_controller_log(self, message: str, level: str, time: datetime) -> None:
        """
        Internal use only.
        Add LogEntry to the controller_log list.
        """
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
        
        self._controller_log.append(LogEntry(message=message, 
                                            type=matched_level, 
                                            time=time,
                                            after_snapshot=self._is_after_snapshot))
    
    def change_application_status(self, instance: str, application: str, 
                      new_status: ApplicationStatus) -> bool:
        """
        Internal use only.
        Change the status field in an ApplicationStatusReport object.
        """
        if (instance, application) not in self._application_status_map.keys():
            return False
        
        self._application_status_map.get((instance, application)).status = new_status
        return True
    
    def change_instance_status(self, instance: str, new_status: AgentManagementState) -> bool:
        """
        Internal use only.
        Change the status field in an InstanceStatusReport object.
        """
        if instance not in self._instance_status_map.keys():
            return False
        
        self._instance_status_map.get(instance).status = new_status
        return True
    
    def append_instance_log(self, instance: str, message: str, type: LogMessageType) -> bool:
        """
        Internal use only.
        Append LogEntry to a logs list of an IntsnaceStatusReport object.
        """
        if instance not in self._instance_status_map.keys():
            raise ValueError(f"FullResultWrapper: Unable to find instance {instance}")
        
        if type == LogMessageType.NONE:
            return True

        entry = LogEntry(time=datetime.now(), 
                         type=type, 
                         message=message,
                         after_snapshot=self._is_after_snapshot)
        self._instance_status_map[instance].logs.append(entry)
        return True
    
    def add_instance_preserved_files(self, instance: str, target: str, amount: int) -> bool:
        """
        Internal use only.
        Change the preserve field in an InstanceStatusReport object.
        """
        if instance not in self._instance_status_map.keys():
            return False
        
        self._instance_status_map.get(instance).preserve = (target, amount)
        return True
    
    def add_data_point(self, point: Dict) -> bool:
        """
        Internal use only.
        Add a data point from an Application time series to the data_series
        list of an ApplicationStatusReport object.
        """
        tags = point.get("tags", None)
        if tags is None:
            return False

        instance = tags.get("instance", None)
        application = tags.get("application", None)

        if (instance, application) not in self._application_status_map.keys():
            return False
        
        self._application_status_map.get((instance, application)).data_series.append(point)
        return True
    
    def _sort_log_entries(self, entries: List[LogEntry]) -> None:
        entries.sort(key=lambda e: e.time)
    
    def get_instance_logs(self, instance: str, 
                          filter: LogMessageType = LogMessageType.NONE) -> List[LogEntry]:
        """
        Retrieve the logs of a specific Instance.

        Args:
            instance (str): Name of the Instance
            filter (LogMessageType): Type of logs to retrieve, use LogMessageType.NONE
                            to disable this filter. Default: LogMessageType.NONE
        
        Returns:
            List[LogEntry]: List of LogEntries for the selected Instance
        """
        result_list: List[LogEntry] = []

        if instance not in self._instance_status_map.keys():
            raise ValueError(f"Unknown instance '{instance}'")
        
        for entry in self._instance_status_map[instance].logs:
            if entry.type.priority >= filter.priority:
                result_list.append(entry)

        self._sort_log_entries(result_list)
        return result_list


    def get_application_logs(self, instance: str, application: str, 
                             filter: LogMessageType = LogMessageType.NONE) -> List[LogEntry]:
        """
        Retrieve the logs of a specific Application on a specific Instance.

        Args:
            instance (str): Name of the Instance
            application (str): Name of the Application
            filter (LogMessageType): Type of logs to retrieve, use LogMessageType.NONE
                            to disable this filter. Default: LogMessageType.NONE
        
        Returns:
            List[LogEntry]: List of LogEntries for the selected Application and
                            Instance
        """
        result_list: List[LogEntry] = []

        if (instance, application) not in self._application_status_map.keys():
            raise ValueError(f"Unknown application '{application}' of instance '{instance}'")
        
        app_entry = self._application_status_map.get((instance, application))
        for entry in  app_entry.logs:
            if entry.type.priority >= filter.priority:
                result_list.append(entry)

        self._sort_log_entries(result_list)
        return result_list
    
    def get_controller_logs(self, filter: LogMessageType = LogMessageType.NONE) -> List[LogEntry]:
        """
        Retrieve the logs of the testbed controller.

        Args:
            filter (LogMessageType): Type of logs to retrieve, use LogMessageType.NONE
                            to disable this filter. Default: LogMessageType.NONE
        
        Returns:
            List[LogEntry]: List of LogEntries of the controller
        """
        result_list = List[LogEntry] = []

        for entry in self._controller_log:
            if entry.type.priority >= filter.priority:
                result_list.append(entry)

        self._sort_log_entries(result_list)
        return result_list
    
    def get_combined_logs(self, instance: str, application: str, 
                          filter: LogMessageType = LogMessageType.NONE) -> List[LogEntry]:
        """
        Retrieve the combined logs of a specific Instance with a specific Application.

        Args:
            instance (str): Name of the Instance
            application (str): Name of the Application
            filter (LogMessageType): Type of logs to retrieve, use LogMessageType.NONE
                            to disable this filter. Default: LogMessageType.NONE
        
        Returns:
            List[LogEntry]: List of LogEntries for the selected Instance and
                            Application
        """
        instance_logs = self.get_instance_logs(instance, filter)
        application_logs = self.get_application_logs(instance, application, filter)
        instance_logs.extend(application_logs)
        self._sort_log_entries(instance_logs)
        return instance_logs
    
    def dump_state(self, file=sys.stdout) -> None:
        """
        Output the state of the FullResultWrapper to a file in a human-readable 
        format (e.g., for debugging purposes).

        Args:
            file (file): File pointer to output to. Default: sys.stdout
        """
        print(f"### BEGIN DUMP Experiment: {self.experiment_tag}, success={self.testbed_succeeded}", file=file)
        print(f"Controller failed: {self.controller_failed}", file=file)
        print(f"Integration failed: {self.integration_failed}", file=file)
        print(f"Testbed Config failed: {self.configuration_failed}\n", file=file)

        print("APPLICATIONS \n", file=file)
        for tup, application in self._application_status_map.items():
            instance, name = tup
            print(f"----- {name}@{instance}: {application.status}", file=file)
            print("Logs:", file=file)
            for log in application.logs:
                print(f"{log.time.isoformat()} - {log.type.prefix} {log.message} {'(X)' if log.after_snapshot else ''}", file=file)

            print("Datapoints:", file=file)
            for entry in application.data_series:
                print(f"{entry}", file=file)

        print("\nINSTANCES\n", file=file)
        for name, instance in self._instance_status_map.items():
            print(f"----- {name}: {instance.status}", file=file)

            if instance.preserve is not None:
                print(f"Preserved {instance.preserve[1]} files to {instance.preserve[0]}", file=file)

            print("Logs:", file=file)
            for log in instance.logs:
                print(f"{log.time.isoformat()} - {log.type.prefix} {log.message} {'(X)' if log.after_snapshot else ''}", file=file)

        print("\nCONTROLLER LOG\n", file=file)
        for log in self._controller_log:
            print(f"{log.time.isoformat()} - {log.type.prefix} {log.message} {'(X)' if log.after_snapshot else ''}", file=file)

        print(f"### END DUMP Experiment: {self.experiment_tag}, success={self.testbed_succeeded}", file=file)
