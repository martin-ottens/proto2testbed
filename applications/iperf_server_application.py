import traceback

from typing import Tuple, Optional, List

from applications.base_application import *
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

    def start(self, runtime: int) -> bool:
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

    def get_export_mapping(self, subtype: ExportSubtype) -> Optional[List[ExportResultMapping]]:
        match subtype.name:
            case "iperf-udp-server":
                return [
                    ExportResultMapping(
                        name="transfer",
                        type=ExportResultDataType.DATA_SIZE,
                        description="Transfer Size"
                    ),
                    ExportResultMapping(
                        name="bitrate",
                        type=ExportResultDataType.DATA_RATE,
                        description="Transfer Bitrate"
                    ),
                    ExportResultMapping(
                        name="jitter",
                        type=ExportResultDataType.MILLISECONDS,
                        description="Transfer Jitter"
                    ),
                    ExportResultMapping(
                        name="datagrams_lost",
                        type=ExportResultDataType.COUNT,
                        description="Number of lost UDP datagrams"
                    ),
                    ExportResultMapping(
                        name="datagrams_total",
                        type=ExportResultDataType.COUNT,
                        description="Number of total UDP datagrams"
                    )
                ]
            case "iperf-tcp-server":
                return [
                    ExportResultMapping(
                        name="transfer",
                        type=ExportResultDataType.DATA_SIZE,
                        description="Transfer Size"
                    ),
                    ExportResultMapping(
                        name="bitrate",
                        type=ExportResultDataType.DATA_RATE,
                        description="Transfer Bitrate"
                    )
                ]
            case _:
                raise Exception(f"Unknown subtype '{subtype.name}' for iperf-server application")
