from abc import ABC, abstractmethod
from common.application_configs import ApplicationConfig

from applications.influxdb_adapter import InfluxDBAdapter

class BaseApplication(ABC):
    def get_runtime_upper_bound(self, runtime: int) -> int:
        return runtime

    @abstractmethod
    def start_collection(self, settings: ApplicationConfig, runtime: int, adapter: InfluxDBAdapter) -> bool:
        pass
