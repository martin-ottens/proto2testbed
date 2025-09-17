#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2024-2025 Martin Ottens
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
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from common.application_configs import ApplicationConfig, AppStartStatus
from common.interfaces import JSONMessage

class ApplicationStatus(Enum):
    UNCHANGED = "unchanged"
    INITIALIZED = "initialized"
    EARLY_FAILED = "loadfailed"
    EXECUTION_STARTED = "started"
    EXECUTION_FINISHED = "finished"
    EXECUTION_FAILED = "failed"

    def __str__(self):
        return str(self.value)
    
    @staticmethod
    def from_str(status: str):
        try: return ApplicationStatus(status)
        except Exception:
            return ApplicationStatus.UNCHANGED

# TODO: Rename
class LogMessageType(Enum):
    NONE = "none", None
    MSG_SUCCESS = "msg_success", "[SUCCESS] "
    MSG_INFO = "msg_info", "[INFO] "
    MSG_DEBUG = "msg_debug", "[DEBUG] "
    MSG_WARNING = "msg_warning", "[WARNING] "
    MSG_ERROR = "msg_error", "[ERROR] "
    STDOUT = "stdout", "[STDOUT] "
    STDERR = "stderr", "[STDERR] "

    def __init__(self, key: str, prefix: str):
        self._key = key
        self._prefix = prefix

    def __str__(self):
        return self._key
    
    @property
    def prefix(self):
        return self._prefix
    
    @staticmethod
    def from_str(key: str):
        for item in LogMessageType:
            if item._key == key:
                return item

        return LogMessageType.NONE

@dataclass
class ExtendedApplicationMessage:
    application: str
    status: ApplicationStatus
    log_message_type: LogMessageType = LogMessageType.NONE
    log_message: Optional[str] = None
    print_to_user: bool = False
    store_in_log: bool = True

@dataclass
class ExtendedLogMessage:
    log_message_type: LogMessageType
    message: str
    print_to_user: bool = False
    store_in_log: bool = True


class InstanceMessageType(Enum):
    STARTED = "started"
    INITIALIZED = "initialized"
    DATA_POINT = "data_point"
    #MSG_SUCCESS = "msg_success" # TODO: Remove
    #MSG_INFO = "msg_info" # TODO: Remove
    #MSG_WARNING = "msg_warning" # TODO: Remove
    #MSG_DEBUG = "msg_debug" # TODO: Remove
    #MSG_ERROR = "msg_error" # TODO: Remove
    FAILED = "failed"
    APPS_INSTALLED = "apps_installed"
    APPS_FAILED = "apps_failed"
    #APP_STARTED_SIGNAL = "app_started" # -> TODO: Extended Status
    #APP_FINISHED_SIGNAL = "app_finished" # -> TODO: Extended Status
    APPS_DONE = "apps_done"
    APPS_EXTENDED_STATUS = "apps_extended_status"
    SYSTEM_EXTENDED_LOG = "system_extended_log"
    FINISHED = "finished"
    COPIED_FILE = "copied_file"
    SHUTDOWN = "shutdown"
    UNKNOWN = "unknown"

    def __str__(self):
        return str(self.value)
    
    @staticmethod
    def from_str(status: str):
        try: return InstanceMessageType(status)
        except Exception:
            return InstanceMessageType.UNKNOWN

# Downstream: Instance -> Controller
# Upstream:   Controller -> Instance

class InstanceManagerMessageDownstream(JSONMessage):
    def __init__(self, name: str, status: InstanceMessageType, 
                 payload: Any = None) -> None:
        self.name = name
        self.status = status
        self.payload = payload


class UpstreamMessage(JSONMessage):
    pass


class InitializeMessageUpstream(UpstreamMessage):
    def __init__(self, script: Optional[str], 
                 environment: Optional[Dict[str, str]]) -> None:
        self.script = script
        self.environment = environment


class InstallApplicationsMessageUpstream(UpstreamMessage):
    def __init__(self, applications: Optional[List[ApplicationConfig]] = None) -> None:
        self.applications = applications


class RunApplicationsMessageUpstream(UpstreamMessage):
    def __init__(self, t0: float) -> None:
        self.t0 = t0


class ApplicationStatusMessageUpstream(UpstreamMessage):
    def __init__(self, app_name: str, app_status: AppStartStatus) -> None:
        self.app_name = app_name
        self.app_status = app_status


class CopyFileMessageUpstream(UpstreamMessage):
    def __init__(self, source: str, target: str, 
                 source_renameto: Optional[str], proc_id: str) -> None:
        self.source = source
        self.source_renameto = source_renameto
        self.target = target
        self.proc_id = proc_id


class FinishInstanceMessageUpstream(UpstreamMessage):
    def __init__(self, preserve_files: Optional[List[str]] = None, 
                 do_preserve: bool = True) -> None:
        self.preserve_files = preserve_files
        self.do_preserve = do_preserve

