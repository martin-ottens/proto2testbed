from abc import ABC, abstractmethod
from common.collector_configs import CollectorConfig

class BaseCollector(ABC):
    @abstractmethod
    def start_collection(self, settings: CollectorConfig, runtime: int = -1) -> None:
        pass
