from abc import ABC, abstractmethod
from common.application_configs import ApplicationConfig

from application_interface import ApplicationInterface

class BaseApplication(ABC):
    def get_runtime_upper_bound(self, runtime: int) -> int:
        return runtime

    @abstractmethod
    def start_collection(self, settings: ApplicationConfig, runtime: int, adapter: ApplicationInterface) -> bool:
        pass
