from abc import ABC, abstractmethod
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass
from enum import Enum

from common.application_configs import ApplicationSettings
from applications.generic_application_interface import GenericApplicationInterface

@dataclass
class ExportSubtype:
    name: str
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
        return str(x)

    MILLISECONDS = "ms", format_identity
    SECONDS = "s", format_identity
    DATA_SIZE = "bytes", format_datasize
    DATA_RATE = "bits/s", format_datarate
    COUNT = "", format_identity

    def __call__(self, *args, **kwargs):
        self.value[1](*args, **kwargs)

@dataclass
class ExportResultMapping:
    name: str
    type: ExportResultDataType
    description: str
    additional_selectors: Optional[Dict[str, str]] = None
    title_suffix: Optional[str] = None

class BaseApplication(ABC):
    API_VERSION = "1.0"
    NAME = "##DONT_LOAD##"

    def __init__(self):
        self.interface = None
        self.settings = None

    def attach_interface(self, interface: GenericApplicationInterface):
        self.interface = interface

    def get_runtime_upper_bound(self, runtime: int) -> int:
        return runtime

    @abstractmethod
    def set_and_validate_config(self, config: ApplicationSettings) -> Tuple[bool, Optional[str]]:
        pass

    @abstractmethod
    def start(self, runtime: int) -> bool:
        pass

    def exports_data(self) -> bool:
        return True

    def get_export_mapping(self, subtype: ExportSubtype) -> Optional[List[ExportResultMapping]]:
        return None
