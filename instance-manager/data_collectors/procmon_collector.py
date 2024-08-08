from data_collectors.base_collector import BaseCollector
from common.collector_configs import CollectorConfig, ProcmonCollectorConfig

class ProcmonCollector(BaseCollector):
    def start_collection(self, settings: CollectorConfig, runtime: int) -> bool:
        if not isinstance(settings, ProcmonCollectorConfig):
            raise Exception("Received invalid config type!")
        pass
