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

"""
Common functions/parsers for "iperf_server_application.py" and "iperf_client_application.py".
No loadable Applications are contained in this file.

Written for iperf 3.12 (cJSON 1.7.15) -> Debian 12

TCP: Client: [ ID] Interval           Transfer     Bitrate         Retr  Cwnd
     Server: [ ID] Interval           Transfer     Bitrate
UDP: Client: [ ID] Interval           Transfer     Bitrate         Total Datagrams
     Server: [ ID] Interval           Transfer     Bitrate         Jitter    Lost/Total Datagrams
"""

import subprocess
import re

from typing import List
from enum import Enum

from applications.generic_application_interface import GenericApplicationInterface


class IPerfMode(Enum):
    UNKNOWN = 0,
    TCP_CLIENT = 1,
    TCP_SERVER = 2,
    UDP_CLIENT = 3,
    UDP_SERVER = 4


class LogPosition(Enum):
    PREAMBLE = 1,
    RUNNING = 2,
    SUMMARY = 3


def size_to_bytes(size: float, unit: str) -> int:
    match unit:
        case "Bytes":
            return size
        case "KBytes":
            return size * 1024
        case "MBytes":
            return size * 1024 * 1024
        case "GBytes":
            return size * 1024 * 1024 * 1024
        case _:
            raise Exception(f"Unknown data size unit '{unit}'")


def rate_to_bytes(bits: float, unit: str) -> int:
    match unit:
        case "bits/sec":
            return bits
        case "Kbits/sec":
            return bits * 1000
        case "Mbits/sec":
            return bits * 1000 * 1000
        case "Gbits/sec":
            return bits * 1000 * 1000 * 1000
        case _:
            raise Exception(f"Unknown data rate unit '{unit}'")


def parse_line_tcp_client(interface: GenericApplicationInterface, time, stream, line):
    if len(line) != 7:
        raise Exception(f"Invalid iperf3 log line received.")
    
    data = {
        "time": time,
        "stream": stream,
        "transfer": size_to_bytes(float(line[0]), line[1]),
        "bitrate": rate_to_bytes(float(line[2]), line[3]),
        "retransmit": int(line[4]),
        "congestion": size_to_bytes(float(line[5]), line[6])
    }
    
    interface.data_point("iperf-tcp-client", data)



def parse_line_tcp_server(interface: GenericApplicationInterface, time, stream, line):
    if len(line) != 4:
        raise Exception(f"Invalid iperf3 log line received.")

    data = {
        "time": time,
        "stream": stream,
        "transfer": size_to_bytes(float(line[0]), line[1]),
        "bitrate": rate_to_bytes(float(line[2]), line[3]),
    }
    
    interface.data_point("iperf-tcp-server", data)


def parse_line_udp_client(interface: GenericApplicationInterface, time, stream, line):
    if len(line) != 5:
        raise Exception(f"Invalid iperf3 log line received.")
    
    data = {
        "time": time,
        "stream": stream,
        "transfer": size_to_bytes(float(line[0]), line[1]),
        "bitrate": rate_to_bytes(float(line[2]), line[3]),
        "datagrams": int(line[4])
    }
    
    interface.data_point("iperf-udp-client", data)


def parse_line_udp_server(interface: GenericApplicationInterface, time, stream, line):
    if len(line) != 8:
        raise Exception(f"Invalid iperf3 log line received.")

    dgram = line[6].split("/")

    data = {
        "time": time,
        "stream": stream,
        "transfer": size_to_bytes(float(line[0]), line[1]),
        "bitrate": rate_to_bytes(float(line[2]), line[3]),
        "jitter": float(line[4]),
        "datagrams_lost": int(dgram[0]),
        "datagrams_total": int(dgram[1])
    }
    
    interface.data_point("iperf-udp-server", data)


def run_iperf(cli: List[str], interface: GenericApplicationInterface, 
              report_startup: bool = False) -> int:

    process = subprocess.Popen(cli, shell=False, 
                               stdout=subprocess.PIPE, 
                               stderr=subprocess.PIPE)
    
    mode = IPerfMode.UNKNOWN
    pos = LogPosition.PREAMBLE
    next_could_be_delimiter = False
    preamble_finished = False
    startup_reported = not report_startup

    while process.poll() is None:
        line = process.stdout.readline().decode("utf-8")
        if line is None or line == "":
            break

        if pos == LogPosition.SUMMARY:
            continue

        if pos == LogPosition.PREAMBLE and not line.startswith("["):
            # Call report_start() BEFORE first client connects. iPerf3 is 
            # ready as soon as first stdout output is written
            if not startup_reported:
                interface.report_startup()
                startup_reported = True

            continue
        else:
            pos = LogPosition.RUNNING
            preamble_finished = True

        if pos == LogPosition.RUNNING and line.startswith("-") and not next_could_be_delimiter:
            pos = LogPosition.SUMMARY
            continue

        next_could_be_delimiter = False

        if pos == LogPosition.RUNNING and "ID" in line and not preamble_finished:
            pos = LogPosition.SUMMARY
            continue

        preamble_finished = False

        if pos == LogPosition.RUNNING:
            if not line.startswith("["):
                raise Exception("Invalid iperf3 log output!")
            if mode == IPerfMode.UNKNOWN:
                if "ID]" in line:
                    if "Jitter" in line: # Order matters!
                        mode = IPerfMode.UDP_SERVER
                    elif "Total Datagrams" in line:
                        mode = IPerfMode.UDP_CLIENT
                    elif "Cwnd" in line:
                        mode = IPerfMode.TCP_CLIENT
                    else:
                        mode = IPerfMode.TCP_SERVER
                continue

            # Do the real parsing
            match_brackets = re.search(r'\[\s*(\d+|SUM)\s*\]', line)
            stream = match_brackets.group(1) if match_brackets else None
            if stream is None:
                raise Exception("Unable to parse iperf3 logline!")

            match_after_brackets = re.search(r'\]\s*(.*)', line)
            everything_after_brackets = match_after_brackets.group(1) if match_after_brackets else None
            if everything_after_brackets is None:
                raise Exception("Unable to parse iperf3 logline!")
            line = everything_after_brackets

            line_parts = line.split()
            if len(line_parts) < 3:
                raise Exception("Unable to parse iperf3 logline!")
            
            time_spec = float(line_parts.pop(0).split("-")[0])
            line_parts.pop(0) # sec

            if "SUM" in stream:
                next_could_be_delimiter = True
                continue

            stream = int(stream)
            line_parts = list(map(lambda x: x.strip(), line_parts))

            match mode:
                case IPerfMode.TCP_CLIENT:
                    parse_line_tcp_client(interface, time_spec, stream, line_parts)
                case IPerfMode.TCP_SERVER:
                    parse_line_tcp_server(interface, time_spec, stream, line_parts)
                case IPerfMode.UDP_CLIENT:
                    parse_line_udp_client(interface, time_spec, stream, line_parts)
                case IPerfMode.UDP_SERVER:
                    parse_line_udp_server(interface, time_spec, stream, line_parts)

    rc = process.wait()
    if rc != 0:
        raise Exception(process.stderr.readline().decode("utf-8"))
    
    if mode == IPerfMode.UNKNOWN:
        raise Exception("Unable to complete iperf log parsing!")
    
    return rc
