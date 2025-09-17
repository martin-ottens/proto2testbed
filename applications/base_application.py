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
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass
from enum import Enum

from common.application_configs import ApplicationSettings
from applications.generic_application_interface import GenericApplicationInterface

"""
This is a generic/abstract class. It contains nothing that can be directly 
loaded as an Application in your Testbed Configuration.
"""

# Represents a data series inside the InfluxDB, passed to an Application so that
# it is able to calculate more details that are used for data export
@dataclass
class ExportSubtype:
    # Name of the measurement obtained from the InfluxDB
    name: str

    # Additional tags that were set for the measurement
    options: Optional[Dict[str, str]] = None


class ExportResultDataType(Enum):
    def format_datasize(x, pos):
        if x >= 1e9:
            return f'{x / 1e9:.1f} GB'
        elif x >= 1e6:
            return f'{x / 1e6:.1f} MB'
        elif x >= 1e3:
            return f'{x / 1e3:.1f} KB'
        else:
            return f'{x:.1f} B'
    
    def format_datarate(x, pos):
        if x >= 1e9:
            return f'{x / 1e9:.1f} Gbps'
        elif x >= 1e6:
            return f'{x / 1e6:.1f} Mbps'
        elif x >= 1e3:
            return f'{x / 1e3:.1f} Kbps'
        else:
            return f'{x:.1f} bps'
    
    def format_identity(x, pos):
        return f"{x:.2f}"

    # Plot axis unit, csv file header, formatter function for plot
    MILLISECONDS = "ms", "ms", format_identity
    SECONDS = "s", "s", format_identity
    DATA_SIZE = "bytes", "bytes", format_datasize
    DATA_RATE = "bits/s", "bps", format_datarate
    COUNT = "", "count", format_identity

    def __call__(self, *args, **kwargs):
        self.value[2](*args, **kwargs)

# Represents a data series for the export that is obtained from the InfluxDB and 
# prepared for export based on this class.
# A series a time series for a single sub-measurement from within a measurement.
@dataclass
class ExportResultMapping:
    # Human-readable name of the data series
    name: str

    # Data formatter for the series
    type: ExportResultDataType

    # Description for Matplotlib y-axis title
    description: str

    # Additional tag selectors to obtain the right data series when multiple 
    # sub-measurements can be matched by the common tags (instance, experiment, 
    # application). These selectors are appended to the these common tags when
    # the data is selected from the InfluxDB. Optional.
    additional_selectors: Optional[Dict[str, str]] = None

    # Suffix for the Matplotlib plot title. Optional.
    title_suffix: Optional[str] = None


class BaseApplication(ABC):
    # API version of the Application, currently only 1.0 is used (optional)
    API_VERSION = "1.0"

    # Name of the Application. Used to referenced bundled Applications, for logging and data labeling.
    NAME = "##DONT_LOAD##"

    def __init__(self):
        self.interface = None
        self.settings = None

    # Do not overwrite. Set the ApplicationInterface for this Application, which is used
    # to interact with the Instance Manager.
    def attach_interface(self, interface: GenericApplicationInterface):
        self.interface = interface

    # The config from the Application-specific part of the Application config from the Testbed Package
    # is passed to this method. This method needs to validate this config and store it for later use 
    # (e.g., in the start method). It returns whether the validation was successful, optionally, an
    # error message can be added, that is sent to the Controllers log (use "None" for no message)
    @abstractmethod
    def set_and_validate_config(self, config: ApplicationSettings) -> Tuple[bool, Optional[str]]:
        pass

    # The Application can overwrite the runtime specified in the common Application settings in the
    # Testbed configuration. "runtime" is the setting from the config. This method is called after the
    # config has been set, so access to the Application Settings are possible to calculate the value.
    # This method should never change the object's state resorting on the "runtime" argument.
    # Optional, when omitted, "runtime" is returned.
    def get_runtime_upper_bound(self, runtime: int) -> int:
        return runtime

    # Start the Application and run for "runtime" seconds, which is the value from the common 
    # Application settings in the Testbed Package. "runtime" can be null when the Application is
    # used as a daemon process. Must be implemented in a blocking way and returns whether the
    # execution was successful. This method may be interrupted when the upper runtime bound 
    # returned by get_runtime_upper_bound is exceeded.
    # This method should not report errors with exceptions, use the extended application message
    # interface provided by the ApplicationInterface for this.
    @abstractmethod
    def start(self, runtime: Optional[int]) -> bool:
        pass

    # The Application is assumed to be started when initialize. Whenever an Application needs to
    # report the startup delayed (e.g. after a server is started), override this method with a 
    # "pass" and call "self.interface.report_startup()" in the start-method. 
    # self.interface.report_startup() MUST be called before start() returns!
    def report_startup(self) -> None:
        if self.interface is not None:
            self.interface.report_startup()

    # Return whether this Application exports any data to the InfluxDB. Used for data export, self.interface
    # is not set.
    def exports_data(self) -> bool:
        return True

    # Returns a data mapping for data export. "subtype" describes an entry from the InfluxDB with the
    # name of the measurement and additional tag. From the "subtype" and the settings in the Application
    # config (which is always set when this method is called) all valid data series are returned as list
    # of ExportResultMappings. Optional, not called when exports_data returns False. self.interface is
    # not set and cannot be used.
    def get_export_mapping(self, subtype: ExportSubtype) -> Optional[List[ExportResultMapping]]:
        return None
