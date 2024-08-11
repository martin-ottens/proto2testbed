from abc import ABC, abstractmethod
from common.collector_configs import CollectorConfig

from data_collectors.influxdb_adapter import InfluxDBAdapter

class BaseCollector(ABC):
    def get_runtime_upper_bound(self, runtime: int) -> int:
        return runtime

    @abstractmethod
    def start_collection(self, settings: CollectorConfig, runtime: int, adapter: InfluxDBAdapter) -> bool:
        pass
