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

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Dict, Any

"""
This is a generic/abstract class. It contains nothing that can be directly 
loaded as an Application in your Testbed Configuration.
"""

class LogMessageLevel(Enum):
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    DEBUG = "DEBUG"
    WARNING = "WARNING"

    def __str__(self):
        return str(self.value)
    
    @staticmethod
    def from_str(level: str):
        return LogMessageLevel(level)


# For data export, the Testbed Controller needs to instantiate all Application -
# in this case the ApplicationInterface is not used inside the Application, so this
# generic version can be used. In the Instance Manager, the functionality of the 
# ApplicationInterface is required, therefore an implementation can be found at
# 'instance-manager/src/application_interface.py', that is passed to the Applications
# when executed via the Instance Manager.
class GenericApplicationInterface(ABC):
    def __init__(self, app_name: str, socket_path: str) -> None:
        self.app_name = app_name
        self.socket_path = socket_path
    
    # Connect to the Instance Manager socket. Is called before the Application 
    # is started, so it must not be used from inside an Application.
    @abstractmethod
    def connect(self):
        pass

    # Disconnect from the Instance Manager socket. Is called after the Application
    # is completed, so it must not be used from inside an Application.
    @abstractmethod
    def disconnect(self):
        pass

    # Send a log message to the Testbed Controller. See the `im log` command for
    # reference.
    @abstractmethod
    def log(self, level: LogMessageLevel, message: str) -> bool:
        pass

    # Report successful Application startup to the controller
    @abstractmethod
    def report_startup(self) -> None:
        pass
    
    # Push a data point to the InfluxDB. See the `im data` command for reference.
    @abstractmethod
    def data_point(self, series_name: str, 
                   points: Dict[str, int | float], 
                   additional_tags: Optional[Dict[str, str]] = None) -> bool:
        pass

    # Mark a file or directory for preservation. See the `im preserve` command
    # for reference.
    @abstractmethod
    def preserve_file(self, path: str) -> bool:
        pass
