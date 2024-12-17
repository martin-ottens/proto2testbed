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
Wraps iPerf3 in client mode ('iperf3 -c') to perform speed tests. Connects to the
iPerf3 server at "host" and "port" (optional, defaults to 5201). The following 
additional settings can be enabled:
- "reverse", boolean: Reverse the data transfer (server to client, default false)
- "udp", boolean: Use UDP instead of TCP (bandwidth_kbps required, default false)
- "streams", int: Number of streams for data transfer (default 1)
- "bandwidth_kbps", int: Data rate for UDP tests
- "tcp_no_delay", boolean: Enable TCP_NO_DELAY (default false)
This Application pushes all interim status reports from iPerf3 to the InfluxDB, 
the conclusion after the test is completed is not considered. The interval of the
reports can be changed with "report_interval" (defaults to 1).

See 'iperf_server_application.py' for the corresponding server config. If only 
the client- or server-report-output should be stored, use the "dont_store"
option in the common application settings.

Output parsing works with iperf 3.12 (cJSON 1.7.15) (Debian 12 standard install).

Example config:
    {
        "application": "iperf3-client",
        "name": "my-iperf-client",
        "delay": 0,
        "runtime": 60,
        "settings": {
            "host": "10.0.0.1", // connect server at 10.0.0.1
            "port": 5201, // connect to port 5201
            "reverse": false, // transfer from client to server
            "udp": true, // use UDP for transfers
            "streams": 1, // use one stream for transfers
            "bandwidth_kbps": 2000, // 2000kbps as UDP data rate
            "tcp_no_delay": false, // TCP_NO_DELAY is disabled
            "report_interval": 5 // report stats every 5 seconds
        }
    }
"""

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
        
    def get_export_mapping(self, subtype: ExportSubtype) -> Optional[List[ExportResultMapping]]:
        match subtype.name:
            case "iperf-udp-client":
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
                        name="datagrams",
                        type=ExportResultDataType.COUNT,
                        description="Number of UDP datagrams"
                    )
                ]
            case "iperf-tcp-client":
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
                        name="retransmit",
                        type=ExportResultDataType.COUNT,
                        description="Number of Retransmits"
                    ),
                    ExportResultMapping(
                        name="congestion",
                        type=ExportResultDataType.DATA_SIZE,
                        description="Congestion Window Size"
                    )
                ]
            case _:
                raise Exception(f"Unknown subtype '{subtype.name}' for iperf-client application")
