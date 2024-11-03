from abc import ABC, abstractmethod
from common.application_configs import ApplicationConfig

from application_interface import ApplicationInterface

class BaseApplication(ABC):
    def __init__(self, adapter: ApplicationInterface):
        self.adapter = adapter

    def get_runtime_upper_bound(self, runtime: int) -> int:
        return runtime

    @abstractmethod
    def set_and_validate_config(self, config: ApplicationConfig) -> bool:
        pass

    @abstractmethod
    def start(self, runtime: int) -> bool:
        pass
