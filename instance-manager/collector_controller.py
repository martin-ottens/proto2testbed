from common.collector_configs import Collectors, ExperimentConfig

from data_collectors.base_collector import BaseCollector
from data_collectors.iperf_client_collector import IperfClientCollector
from data_collectors.iperf_server_collector import IperfServerCollector
from data_collectors.ping_collector import PingCollector
from data_collectors.procmon_collector import ProcmonCollector

class CollectorController():
    @classmethod
    def map_collector(collector: Collectors) -> BaseCollector:
        match collector:
            case Collectors.IPERF3_SERVER:
                return IperfServerCollector()
            case Collectors.IPERF3_CLIENT:
                return IperfClientCollector()
            case Collectors.PING:
                return PingCollector()
            case Collectors.PROCMON:
                return ProcmonCollector()
            case _:
                raise Exception(f"Unmapped Collector {collector}")
            
    def __init__(self, config: ExperimentConfig) -> None:
        self.config = config
        self.collector = CollectorController.map_collector(config.collector)
        self.settings = config.settings

    def __run(self):
        pass

    def start(self):
        pass

    def has_terminated(self):
        pass
