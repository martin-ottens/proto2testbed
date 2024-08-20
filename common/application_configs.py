from abc import ABC
from enum import Enum

from typing import List, Dict, Optional

from common.interfaces import JSONSerializer

class Applications(str, Enum):
    IPERF3_SERVER = "iperf3-server"
    IPERF3_CLIENT = "iperf3-client"
    PING = "ping"
    PROCMON = "procmon"
    RUN_PROGRAM = "run-program"

    def __str__(self):
        return str(self.value)

class ApplicationConfig(ABC):
    pass

class IperfServerApplicationConfig(ApplicationConfig, JSONSerializer):
    def __init__(self, host: str = "0.0.0.0", port: int = 5201, 
                 report_interval: int = 1) -> None:
        self.host = host
        self.port = port
        self.report_interval = report_interval
        

class IperfClientApplicationConfig(ApplicationConfig, JSONSerializer):
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

class PingApplicationConfig(ApplicationConfig, JSONSerializer):
    def __init__(self, target: str, source: str = None, interval: int = 1,
                 packetsize: int = None, ttl: int = None, timeout: int = 1) -> None:
        self.target = target
        self.source = source
        self.interval = interval
        self.packetsize = packetsize
        self.ttl = ttl
        self.timeout = timeout

class ProcmonApplicationConfig(ApplicationConfig, JSONSerializer):
    def __init__(self, interval: int = 1, interfaces: List[str] = None,
                 processes: List[str] = None, system: bool = True) -> None:
        self.interval = interval
        self.interfaces = interfaces
        self.processes = processes
        self.system = system

class RunProgramApplicationConfig(ApplicationConfig, JSONSerializer):
    def __init__(self, command: str, ignore_timeout: bool = False, 
                 environment: Optional[Dict[str, str]] = None) -> None:
        self.command = command
        self.ignore_timeout = ignore_timeout
        self.environment = environment

class ApplicationConfig(JSONSerializer):
    def __init__(self, name: str, application: str, delay: int = 0, 
                 runtime: int = 30, dont_store: bool = False, settings = None) -> None:
        self.name: str = name
        self.delay: int = delay
        self.runtime: int = runtime
        self.dont_store: bool = dont_store

        self.application = Applications(application)

        match self.application:
            case Applications.IPERF3_CLIENT:
                self.settings = IperfClientApplicationConfig(**settings)
            case Applications.IPERF3_SERVER:
                self.settings = IperfServerApplicationConfig(**settings)
            case Applications.PING:
                self.settings = PingApplicationConfig(**settings)
            case Applications.PROCMON:
                self.settings = ProcmonApplicationConfig(**settings)
            case Applications.RUN_PROGRAM:
                self.settings = RunProgramApplicationConfig(**settings)
            case _:
                raise Exception(f"Unkown application type {application}")
