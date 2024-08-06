from data_collectors.base_collector import BaseCollector
from common.collector_configs import CollectorConfig, IperfServerCollectorConfig

class IperfServerCollector(BaseCollector):
    def start_collection(self, settings: CollectorConfig, runtime: int = -1) -> None:
        if not isinstance(settings, IperfServerCollectorConfig):
            raise Exception("Received invalid config type!")
        pass
