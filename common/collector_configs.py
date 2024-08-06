from abc import ABC
from enum import Enum

from common.interfaces import JSONSerializer

class Collectors(str, Enum):
    IPERF3_SERVER = "iperf3-server"
    IPERF3_CLIENT = "iperf3-client"
    PING = "ping"
    PROCMON = "procmon"

    def __str__(self):
        return str(self.value)

class CollectorConfig(ABC):
    pass

class IperfServerCollectorConfig(CollectorConfig, JSONSerializer):
    def __init__(self, host: str = "0.0.0.0", port: int = 5001) -> None:
        self.host = host
        self.port = port
        

class IperfClientCollectorConfig(CollectorConfig, JSONSerializer):
    def __init__(self, host: str, port: int = 5001, reverse: bool = None, 
                 udp: bool = None, streams: int = None, 
                 bandwidth_bps: int = None, tcp_no_delay: bool = None) -> None:
        self.host = host
        self.port = port
        self.reverse = reverse
        self.udp = udp
        self.streams = streams
        self.bandwidth_bps = bandwidth_bps
        self.tcp_no_delay = tcp_no_delay

class PingCollectorConfig(CollectorConfig, JSONSerializer):
    pass

class ProcmonCollectorConfig(CollectorConfig, JSONSerializer):
    pass

class ExperimentConfig(JSONSerializer):
    def __init__(self, name: str, collector: str, delay: int = 0, 
                 timeout: int = -1, settings = None) -> None:
        self.name: str = name
        self.delay: int = delay
        self.timeout: int = timeout

        self.collector = Collectors(collector)

        match self.collector:
            case Collectors.IPERF3_CLIENT:
                self.settings = IperfClientCollectorConfig(**settings)
            case Collectors.IPERF3_SERVER:
                self.settings = IperfServerCollectorConfig(**settings)
            case Collectors.PING:
                self.settings = PingCollectorConfig(**settings)
            case Collectors.PROCMON:
                self.settings = ProcmonCollectorConfig(**settings)
            case _:
                raise Exception(f"Unkown collector type {collector}")
