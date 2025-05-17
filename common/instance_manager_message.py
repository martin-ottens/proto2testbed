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

from common.application_configs import ApplicationConfig, AppStartStatus
from common.interfaces import JSONMessage


class InstanceMessageType(Enum):
    STARTED = "started"
    INITIALIZED = "initialized"
    DATA_POINT = "data_point"
    MSG_SUCCESS = "msg_success"
    MSG_INFO = "msg_info"
    MSG_WARNING = "msg_warning"
    MSG_DEBUG = "msg_debug"
    MSG_ERROR = "msg_error"
    FAILED = "failed"
    APPS_INSTALLED = "apps_installed"
    APPS_FAILED = "apps_failed"
    APP_STARTED_SIGNAL = "app_started"
    APP_FINISHED_SIGNAL = "app_finished"
    APPS_DONE = "apps_done"
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

