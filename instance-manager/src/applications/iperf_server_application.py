import traceback

from typing import Tuple, Optional

from base_application import BaseApplication
from applications.iperf_common import run_iperf
from common.application_configs import ApplicationSettings


class IperfServerApplicationConfig(ApplicationSettings):
    def __init__(self, host: str = "0.0.0.0", port: int = 5201, 
                 report_interval: int = 1) -> None:
        self.host = host
        self.port = port
        self.report_interval = report_interval


class IperfServerApplication(BaseApplication):
    NAME = "iperf3-server"

    def get_runtime_upper_bound(self, runtime: int) -> int:
        return runtime * 2
    
    def set_and_validate_config(self, config: ApplicationSettings) -> Tuple[bool, Optional[str]]:
        try:
            self.settings = IperfServerApplicationConfig(**config)
            return True, None
        except Exception as ex:
            return False, f"Config validation failed: {ex}"

    def start_collection(self, runtime: int) -> bool:
        if self.settings is None:
            return False
        
        command = ["/usr/bin/iperf3", "--forceflush", "--one-off"]

        command.append("--interval")
        command.append(str(self.settings.report_interval))

        command.append("--port")
        command.append(str(self.settings.port))
        command.append("--server")
        command.append(self.settings.host)

        try:
           return run_iperf(command, self.interface) == 0
        except Exception as ex:
            traceback.print_exception(ex)
            raise Exception(f"Iperf3 server error: {ex}")
