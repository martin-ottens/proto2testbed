from data_collectors.base_collector import BaseCollector
from common.collector_configs import CollectorConfig, IperfClientCollectorConfig

class IperfClientCollector(BaseCollector):
    def start_collection(self, settings: CollectorConfig, runtime: int = -1) -> None:
        if not isinstance(settings, IperfClientCollectorConfig):
            raise Exception("Received invalid config type!")
        pass

