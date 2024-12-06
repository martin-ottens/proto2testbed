from abc import ABC, abstractmethod
from typing import Optional, Tuple

from common.application_configs import ApplicationSettings
from applications.generic_application_interface import GenericApplicationInterface


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
