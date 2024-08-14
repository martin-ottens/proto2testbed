from abc import ABC
from enum import Enum

from typing import List

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
    def __init__(self, host: str = "0.0.0.0", port: int = 5201, 
                 report_interval: int = 1) -> None:
        self.host = host
        self.port = port
        self.report_interval = report_interval
        

class IperfClientCollectorConfig(CollectorConfig, JSONSerializer):
    def __init__(self, host: str, port: int = 5201, reverse: bool = None, 
                 udp: bool = None, streams: int = None, report_interval: int = 1, 
                 bandwidth_kbps: int = None, tcp_no_delay: bool = None) -> None:
        self.host = host
        self.port = port
        self.reverse = reverse
        self.udp = udp
        self.streams = streams
        self.bandwidth_kbps = bandwidth_kbps
        self.tcp_no_delay = tcp_no_delay
        self.report_interval = report_interval

class PingCollectorConfig(CollectorConfig, JSONSerializer):
    def __init__(self, target: str, source: str = None, interval: int = 1,
                 packetsize: int = None, ttl: int = None, timeout: int = 1) -> None:
        self.target = target
        self.source = source
        self.interval = interval
        self.packetsize = packetsize
        self.ttl = ttl
        self.timeout = timeout

class ProcmonCollectorConfig(CollectorConfig, JSONSerializer):
    def __init__(self, interval: int = 1, interfaces: List[str] = None,
                 processes: List[str] = None, system: bool = True) -> None:
        self.interval = interval
        self.interfaces = interfaces
        self.processes = processes
        self.system = system

class ExperimentConfig(JSONSerializer):
    def __init__(self, name: str, collector: str, delay: int = 0, 
                 runtime: int = 30, dont_store: bool = False, settings = None) -> None:
        self.name: str = name
        self.delay: int = delay
        self.runtime: int = runtime
        self.dont_store: bool = dont_store

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
