from abc import ABC
from enum import Enum

class Collectors(str, Enum):
    IPERF3_SERVER = "iperf3-server"
    IPERF3_CLIENT = "iperf3-client"

    def __str__(self):
        return str(self.value)

class CollectorConfig(ABC):
    pass

class iPerf3ServerCollector(CollectorConfig):
    def __init__(self, host: str = "0.0.0.0", port: int = 5001) -> None:
        self.host = host
        self.port = port
        

class iPerf3ClientCollector(CollectorConfig):
    def __init__(self, host: str, time: int, port: int = 5001, 
                 reverse: bool = None, udp: bool = None, streams: int = None, 
                 bandwidth_bps: int = None, tcp_no_delay: bool = None) -> None:
        self.host = host
        self.port = port
        self.reverse = reverse
        self.udp = udp
        self.time = time
        self.streams = streams
        self.bandwidth_bps = bandwidth_bps
        self.tcp_no_delay = tcp_no_delay

class ExperimentConfig():
    def __init__(self, json) -> None:
        self.name: str = ""
        self.delay: int = 0, 
        self.timeout: int = -1
        self.__dict__.update(json)

        self.collector = Collectors(self.collector)

        match self.collector:
            case Collectors.IPERF3_CLIENT:
                self.settings = iPerf3ClientCollector(**self.settings)
            case Collectors.IPERF3_SERVER:
                self.settings = iPerf3ServerCollector(**self.settings)
            case _:
                raise Exception(f"Unkown collector type {self.collector}")
    
    def as_dict(self):
        rdict = vars(self).copy()
        rdict["settings"] = vars(self.settings).copy()
        return rdict
