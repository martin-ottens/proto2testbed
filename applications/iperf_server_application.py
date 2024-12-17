#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2024 Martin Ottens
# 
# This program is free software: you can redistribute it and/or modify 
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful, 
# but WITHOUT ANY WARRANTY; without even the implied warranty of 
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the 
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License 
# along with this program. If not, see https://www.gnu.org/licenses/.
#

import traceback

from typing import Tuple, Optional, List

from applications.base_application import *
from applications.iperf_common import run_iperf
from common.application_configs import ApplicationSettings

"""
Wraps iPerf3 in server mode ('iperf3 -s') to perform speed tests. Bind to the
interface and port given as "host" and "port" (optional, defaults to "0.0.0.0"
and 5201). Each output of iPerf is pushed to the InfluxDB, "report_interval"
controls, how often iPerf will report statistics. Only interim reports are 
parsed, the conclusion will not be pushed.
The server only performs one test and terminates (one-off) and will not 
terminate by itself when no client connected. For the runtime and delay, select 
the following values to prevent problems:

DELAYserver = DELAYclient - 1 // Start server 1 second before the client
TIMEOUTserver = max(TIMEOUTclient * 1.1, TIMEOUTclient + 5) // Allow the server to run longer

See 'iperf_client_application.py' for the corresponding client config. If only 
the client- or server-report-output should be stored, use the "dont_store"
option in the common application settings.

Output parsing works with iperf 3.12 (cJSON 1.7.15) (Debian 12 standard install).

Example config:
    {
        "application": "iperf3-server",
        "name": "my-iperf-server",
        "delay": 0,
        "runtime": 60,
        "settings": {
            "host": "0.0.0.0", // bind to 0.0.0.0 (listen on all interfaces)
            "port": 5201, // bind control server to port 5201
            "report_interval": 5 // report stats every 5 seconds
        }
    }
"""

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

