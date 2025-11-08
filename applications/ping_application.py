#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2024-2025 Martin Ottens
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

import subprocess

from typing import Tuple, Optional, List

from applications.base_application import *
from common.application_configs import ApplicationSettings
from common.instance_manager_message import LogMessageType

"""
Wraps the 'ping' command to monitor ICMP RTT and TTL values. "target" is the
IP address or hostname that should be pinged, "source" if the local IP address 
that should be used to send the pings (can be omitted). Pings are sent every 
"interval" seconds (defaults to 1). ICMP ping requests have a size of 
"packetsize" bytes and a TTL of "ttl" hops (both values are optional and 
default to the standard values used by 'ping'). A timeout in seconds for a 
ping reply can be defined with "timeout" (defaults to 1), after that time a 
"-1" value is stored to indicate, that the host is unreachable.

Example config:
    {
        "application": "ping",
        "name": "my-ping",
        "delay": 0,
        "runtime": 60,
        "settings": {
            "target": 10.0.0.2, // host, ICMP echo requests are sent to
            "source": 10.0.0.1, // local source IP address, required when "target" can be reached by multiple way
            "interval": 5, // send request every 5 seconds
            "packetsize": 1024, // packets have a size of 1024 bytes
            "ttl": 20, // packets have a ttl of 20
            "timeout": 2 // if no reply is received within 2 seconds, the host is assumed that the host is unreachable
        }
    }
"""

class PingApplicationConfig(ApplicationSettings):
    def __init__(self, target: str, source: str = None, interval: float = 1,
                 packetsize: int = None, ttl: int = None, timeout: int = 1) -> None:
        self.target = target
        self.source = source
        self.interval = interval
        self.packetsize = packetsize
        self.ttl = ttl
        self.timeout = timeout


class PingApplication(BaseApplication):
    NAME = "ping"

    def set_and_validate_config(self, config: ApplicationSettings) -> Tuple[bool, Optional[str]]:
        try:
            self.settings = PingApplicationConfig(**config)
            return True, None
        except Exception as ex:
            return False, f"Config validation failed: {ex}"

    def start(self, runtime: Optional[int]) -> bool:
        if self.settings is None:
            return False
        
        command = ["/usr/bin/ping", "-O", "-B", "-D",
                   "-W", str(self.settings.timeout),
                   "-i", str(self.settings.interval)]

        if runtime is not None:
            command.append("-w")
            command.append(str(runtime))

        if self.settings.source is not None:
            command.append("-I")
            command.append(self.settings.source)

        if self.settings.ttl is not None:
            command.append("-t")
            command.append(str(self.settings.ttl))

        if self.settings.packetsize is not None:
            command.append("-s")
            command.append(str(self.settings.packetsize))
    
        command.append(self.settings.target)

        try:
            process = subprocess.Popen(command, shell=False, 
                                       stdout=subprocess.PIPE, 
                                       stderr=subprocess.STDOUT)
        except Exception as ex:
            self.interface.push_log_message(f"Unable to start ping: {ex}", 
                                            LogMessageType.MSG_ERROR, 
                                            True)
            return False

        current_seq = 0
        try:
            while process.poll() is None:
                line = process.stdout.readline().decode("utf-8")

                if line is None or line == "":
                    break

                if not line.startswith("["): 
                    continue

                parts = line.split(" ")
                #timestamp = float(parts.pop(0).replace("[", "").replace("]", ""))
                parts.pop(0)

                reachable = True

                if parts[0] == "no" or parts[0] == "From":
                    reachable = False

                results = dict(map(lambda z: (z[0], z[1]), map(lambda y: y.split("="), filter(lambda x: "=" in x, parts))))

                if "icmp_seq" not in results:
                    continue

                icmp_seq = int(results["icmp_seq"])

                if current_seq >= icmp_seq:
                    continue
                current_seq = icmp_seq

                data = {
                    "rtt": float(results.get("time", -1)),
                    "ttl": int(results.get("ttl", -1)),
                    "reachable": reachable,
                    "icmp_seq": icmp_seq
                }

                self.interface.data_point("ping", data)

        except Exception as ex:
            self.interface.push_log_message(f"Ping error: {ex}", 
                                            LogMessageType.MSG_ERROR, 
                                            True)
            return False

        return process.wait() == 0
    
    def get_export_mapping(self, subtype: ExportSubtype) -> Optional[List[ExportResultMapping]]:
        return [
            ExportResultMapping(
                name="rtt",
                type=ExportResultDataType.MILLISECONDS,
                description="ICMP RTT"
            ),
            ExportResultMapping(
                name="reachable",
                type=ExportResultDataType.COUNT,
                description="is target reachable?"
            ),
            ExportResultMapping(
                name="ttl",
                type=ExportResultDataType.COUNT,
                description="TTL of response packet"
            )
        ]
