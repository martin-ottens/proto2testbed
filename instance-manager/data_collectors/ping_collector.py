from data_collectors.base_collector import BaseCollector
from common.collector_configs import CollectorConfig, PingCollectorConfig

class PingCollector(BaseCollector):
    def start_collection(self, settings: CollectorConfig, runtime: int) -> bool:
        if not isinstance(settings, PingCollectorConfig):
            raise Exception("Received invalid config type!")
        pass
