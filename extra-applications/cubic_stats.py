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

import time
import subprocess

from typing import List, Tuple, Optional

from applications.base_application import *
from common.application_configs import ApplicationSettings

"""
Parse 'ss -tipH' to get TCP congestion control stats for a specific list of 
processes ("procs"). Supported congestion control algorithms: cubic
Checks every "interval" seconds (optional, defaults to 1). If an iPerf connection
is monitored, the "iperf_mode" option can be used to disable recording of the 
control process (optional, defaults to false).

Example config:
    {
        "application": "apps/cubic_stats.py",
        "name": "cubic_iperf",
        "delay": 0,
        "runtime": 60,
        "settings": {
            "interval": 1, // every second
            "procs": ["iperf3"], // short name of processes to parse
            "iperf_mode": true // filter iPerf control process
        }
    }
"""

class CubicStatsApplicationConfig(ApplicationSettings):
    def __init__(self, procs: List[str], 
                 interval: int = 1,
                 iperf_mode: bool = False)  -> None:
        self.interval = interval
        self.procs = procs
        self.iperf_mode = iperf_mode

class CubicStatsApplication(BaseApplication):
    NAME = "cubic-stats"

    def set_and_validate_config(self, config: ApplicationSettings) -> Tuple[bool, Optional[str]]:
        try:
            self.settings = CubicStatsApplicationConfig(**config)

            if "iperf3" not in self.settings.procs and self.settings.iperf_mode:
                return False, "iperf3 mode is not possible without iperf3 process"
            else:
                return True, None
        except Exception as ex:
            return False, f"Config validation failed: {ex}"

    def __interpret_bits(self, input: str):
        input = input.replace("bps", "")

        units = {
                "k": 1_000,
                "K": 1_000,
                "M": 1_000_000,
                "G": 1_000_000_000,
                "T": 1_000_000_000_000,
                "b": 1,
                "B": 8,
                "p": 1
            }
        
        if input[-1].isalpha():
            number_part = float(input[:-1])
            
            if input[-1] in units:
                return int(number_part * units[input[-1]])
            else:
                raise Exception(f"Unsupported Unit: {input[-1]}")
        else:
            return int(input)

    def __parse_output(self, input: str):
        results = []
        context = None
        for line in input.split("\n"):
            if line.strip() == "":
                continue

            if not line.startswith((' ', '\t')):
                if context is not None:
                    results.append(context)
                    context = None

                recv_q, send_q, local, remote, proc_dirtry = line.split(maxsplit=4)
                _, proc_dirtry = proc_dirtry.split("((", maxsplit=1)
                prog_dirtry, _, fd_dirtry = proc_dirtry.split(",", maxsplit=2)
                prog = prog_dirtry.replace("\"", "")
                _, fd = fd_dirtry.replace("))", "").split("=", maxsplit=1)

                context = {
                    "_": {
                        "prog": prog,
                        "fd": int(fd)
                    },
                    "recv_q": int(recv_q),
                    "send_q": int(send_q),
                    "send_scale": 0,
                    "recv_scale": 0,
                    "rto": 0,
                    "rtt": 0.0,
                    "rttvar": 0.0,
                    "mss": 0,
                    "cwnd": 0,
                    "pmtu": 0,
                    "bytes_retrans": 0,
                    "bytes_acked": 0,
                    "unacked": 0
                }
                continue

            if context is None:
                continue
            
            line = line.strip()
            if not line.startswith("cubic"):
                continue

            segments = line.split()
            index = 0
            while index < len(segments):
                segment = segments[index]
                if segment.startswith("wscale"):
                    _, wscale = segment.split(":", maxsplit=1)
                    send_scale, recv_scale = wscale.split(",", maxsplit=1)
                    context["send_scale"] = int(send_scale)
                    context["recv_scale"] = int(recv_scale)
                elif segment.startswith("rto"):
                    _, rto = segment.split(":", maxsplit=1)
                    context["rto"] = int(rto)
                elif segment.startswith("rtt"):
                    _, rtt = segment.split(":", maxsplit=1)
                    rtt, rttvar = rtt.split("/", maxsplit=1)
                    context["rtt"] = float(rtt)
                    context["rttvar"] = float(rttvar)
                elif segment.startswith("mss"):
                    _, mss = segment.split(":", maxsplit=1)
                    context["mss"] = int(mss)
                elif segment.startswith("cwnd"):
                    _, cwnd = segment.split(":", maxsplit=1)
                    context["cwnd"] = int(cwnd)
                elif segment.startswith("pmtu"):
                    _, pmtu = segment.split(":", maxsplit=1)
                    context["pmtu"] = int(pmtu)
                elif segment.startswith("bytes_retrans"):
                    _, retrans = segment.split(":", maxsplit=1)
                    context["bytes_retrans"] = self.__interpret_bits(retrans)
                elif segment.startswith("bytes_acked"):
                    _, acked = segment.split(":", maxsplit=1)
                    context["bytes_acked"] = self.__interpret_bits(acked)
                elif segment.startswith("unacked"):
                    _, unacked = segment.split(":", maxsplit=1)
                    context["unacked"] = self.__interpret_bits(unacked)
            
                index += 1
        
        if context is not None:
            results.append(context)

        return results
    
    def __get_one_datapoint(self, input: str):
        contexts = self.__parse_output(input)

        if len(contexts) == 0:
            return

        if self.settings.iperf_mode:
            control_fd = min(map(lambda x: x["_"]["fd"], contexts))
        else:
            control_fd = -1

        for context in contexts:
            prog = context["_"]["prog"]
            fd = context["_"]["fd"]
            del context["_"]

            if prog == "iperf3" and fd == control_fd:
                continue

            if prog not in self.settings.procs:
                continue
            
            self.interface.data_point("cubic-stats", context, {
                "prog": prog,
                "fd": str(fd)
            })

    def start(self, runtime: int) -> bool:
        end_at = time.time() + runtime
        while end_at > time.time():
            proc = subprocess.run(["/usr/bin/ss", "-tipH", "state", "established"], capture_output=True, shell=False)
            if proc.returncode != 0:
                raise Exception(f"Unable to run 'ss' command: {proc.stderr.decode('utf-8')}")
            
            self.__get_one_datapoint(proc.stdout.decode('utf-8'))
            time.sleep(self.settings.interval)
        
        return True
    
    def get_export_mapping(self, subtype: ExportSubtype) -> Optional[List[ExportResultMapping]]:
        return [
            ExportResultMapping(
                name="recv_q",
                type=ExportResultDataType.COUNT,
                description="Receive Queue Length",
                additional_selectors={"fd": subtype.options["fd"]},
                title_suffix=f'Process: {subtype.options["prog"]}'
            ),
            ExportResultMapping(
                name="send_q",
                type=ExportResultDataType.COUNT,
                description="Send Queue Length",
                additional_selectors={"fd": subtype.options["fd"]},
                title_suffix=f'Process: {subtype.options["prog"]}'
            ),
            ExportResultMapping(
                name="send_scale",
                type=ExportResultDataType.COUNT,
                description="Send Scale Factor",
                additional_selectors={"fd": subtype.options["fd"]},
                title_suffix=f'Process: {subtype.options["prog"]}'
            ),
            ExportResultMapping(
                name="recv_scale",
                type=ExportResultDataType.COUNT,
                description="Receive Scale Factor",
                additional_selectors={"fd": subtype.options["fd"]},
                title_suffix=f'Process: {subtype.options["prog"]}'
            ),
            ExportResultMapping(
                name="rto",
                type=ExportResultDataType.MILLISECONDS,
                description="Retramsmit Timeout",
                additional_selectors={"fd": subtype.options["fd"]},
                title_suffix=f'Process: {subtype.options["prog"]}'
            ),
            ExportResultMapping(
                name="rtt",
                type=ExportResultDataType.MILLISECONDS,
                description="TCP Round Trip Time",
                additional_selectors={"fd": subtype.options["fd"]},
                title_suffix=f'Process: {subtype.options["prog"]}'
            ),
            ExportResultMapping(
                name="rttvar",
                type=ExportResultDataType.MILLISECONDS,
                description="TCP RTT Variation",
                additional_selectors={"fd": subtype.options["fd"]},
                title_suffix=f'Process: {subtype.options["prog"]}'
            ),
            ExportResultMapping(
                name="mss",
                type=ExportResultDataType.DATA_SIZE,
                description="Maximum Segment Size",
                additional_selectors={"fd": subtype.options["fd"]},
                title_suffix=f'Process: {subtype.options["prog"]}'
            ),
            ExportResultMapping(
                name="cwnd",
                type=ExportResultDataType.DATA_SIZE,
                description="Congestion Window Size",
                additional_selectors={"fd": subtype.options["fd"]},
                title_suffix=f'Process: {subtype.options["prog"]}'
            ),
            ExportResultMapping(
                name="pmth",
                type=ExportResultDataType.DATA_SIZE,
                description="Discovered Path MTU",
                additional_selectors={"fd": subtype.options["fd"]},
                title_suffix=f'Process: {subtype.options["prog"]}'
            ),
            ExportResultMapping(
                name="bytes_retrans",
                type=ExportResultDataType.DATA_SIZE,
                description="Amount of Retransmitted Bytes",
                additional_selectors={"fd": subtype.options["fd"]},
                title_suffix=f'Process: {subtype.options["prog"]}'
            ),
            ExportResultMapping(
                name="bytes_acked",
                type=ExportResultDataType.DATA_SIZE,
                description="Amount of Acked Bytes",
                additional_selectors={"fd": subtype.options["fd"]},
                title_suffix=f'Process: {subtype.options["prog"]}'
            ),
            ExportResultMapping(
                name="unacked",
                type=ExportResultDataType.DATA_SIZE,
                description="Amount of Unacked Bytes",
                additional_selectors={"fd": subtype.options["fd"]},
                title_suffix=f'Process: {subtype.options["prog"]}'
            )
        ]
