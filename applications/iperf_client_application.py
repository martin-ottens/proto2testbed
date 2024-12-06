import traceback

from typing import Tuple, Optional

from applications.base_application import BaseApplication
from applications.iperf_common import run_iperf
from common.application_configs import ApplicationSettings


class IperfClientApplicationConfig(ApplicationSettings):
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


class IperfClientApplication(BaseApplication):
    NAME = "iperf3-client"

    __CONNECT_TIMEOUT_MULTIPLIER = 0.1
    __STATIC_DELAY_BEFORE_START = 5

    def get_runtime_upper_bound(self, runtime: int) -> int:
        return runtime + int(IperfClientApplication.__CONNECT_TIMEOUT_MULTIPLIER * runtime) + IperfClientApplication.__STATIC_DELAY_BEFORE_START

    def set_and_validate_config(self, config: ApplicationSettings) -> Tuple[bool, Optional[str]]:
        try:
            self.settings = IperfClientApplicationConfig(**config)
            return True, None
        except Exception as ex:
            return False, f"Config validation failed: {ex}"

    def start(self, runtime: int) -> bool:
        if self.settings is None:
            return False
        
        command = ["/usr/bin/iperf3", "--forceflush"]

        if self.settings.reverse is True:
            command.append("--reverse")

        if self.settings.udp is True:
            if self.settings.bandwidth_kbps is None:
                raise Exception("Iperf3 Client UDP Settings needs bandwidth!")
            command.append("--udp")
        
        if self.settings.bandwidth_kbps is not None:
            command.append("--bandwidth")
            command.append(f"{self.settings.bandwidth_kbps}k")
        
        if self.settings.streams is not None:
            command.append("--parallel")
            command.append(str(self.settings.streams))
        
        if self.settings.tcp_no_delay is True:
            if self.settings.udp is True:
                raise Exception("TCP_NO_DELAY is used together with UDP option")
            command.append("--no-delay")
        
        command.append("--time")
        command.append(str(runtime))

        command.append("--interval")
        command.append(str(self.settings.report_interval))

        # --connect-timeout expects ms
        command.append("--connect-timeout")
        command.append(str(max(IperfClientApplication.__STATIC_DELAY_BEFORE_START, 
                               IperfClientApplication.__CONNECT_TIMEOUT_MULTIPLIER * runtime) * 1000))

        command.append("--port")
        command.append(str(self.settings.port))
        command.append("--client")
        command.append(self.settings.host)

        try:
           return run_iperf(command, self.interface) == 0
        except Exception as ex:
            traceback.print_exception(ex)
            raise Exception(f"Iperf3 server error: {ex}")


