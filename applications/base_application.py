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

    # Name of the Applicaton. Used to referenced bundeled Applications, for logging and data labling.
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
    # (e.g., in the start method). It returns, wether the validation was successful, optionally, an 
    # error message can be added, that is send to the Controllers log (use "None" for no message) 
    @abstractmethod
    def set_and_validate_config(self, config: ApplicationSettings) -> Tuple[bool, Optional[str]]:
        pass

    # The Application can overrwrite the runtime specified in the common Application settings in the
    # Testbed configuration. "runtime" is the setting from the config. This method is called after the
    # config has been set, so access to the Application Settings are possible to calculate the value.
    # Optional, when omitted, "runtime" is returned.
    def get_runtime_upper_bound(self, runtime: int) -> int:
        return runtime

    # Start the Application and run for "runtime" seconds, which is the value from the common 
    # Application settings in the Testbed Package. Must be implemented in a blocking way and returns
    # wether the execution was successful. This method may be interrupted when the upper runtime
    # bound returned by get_runtime_upper_bound is exceeded.
    @abstractmethod
    def start(self, runtime: int) -> bool:
        pass

    # Return wether this Application exports any data to the InfluxDB. Used for data export, self.interface
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
