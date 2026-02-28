#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2026 Martin Ottens
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

import os
import subprocess

from pathlib import Path
from typing import Optional, Tuple

from applications.base_application import BaseApplication
from common.application_configs import ApplicationSettings
from common.instance_manager_message import LogMessageType

"""
Create a packet capture using tcpdump, write to an output file that is 
automatically preserved on testbed shutdown. Must have a specified
runtime to limit output file size, optional filters can be applied.
Remember to specify an output path for preserved files upon testbed
startup.

Example config:
    {
        "application": "tcpdump",
        "name": "tcpdump-eth1",
        "delay": 0,
        "runtime": 30,
        "settings": {
            "filename": "out.pcap", // Capture will be preserved to '<out>/<instance>/<filename>'
            "filter": "port 80", // tcpdump filter expression, optional
            "interface": "eth1" // Name of the interface to start the capture on, 'any' is possible and the default
        }
    }
"""

class TcpDumpApplicationConfig(ApplicationSettings):
    def __init__(self, filename: str, filter: Optional[str] = None,
                 interface: str = "any") -> None:
        self.filename = filename
        self.filter = filter
        self.interface = interface


class TcpDumpApplication(BaseApplication):
    NAME = "tcpdump"

    def __init__(self):
        super().__init__()

    def set_and_validate_config(self, config: ApplicationSettings) -> Tuple[bool, Optional[str]]:
        try:
            self.settings = TcpDumpApplicationConfig(**config)

            if self.settings.interface != "any":
                import psutil
                iflist = psutil.net_if_addrs()
                if self.settings.interface not in iflist.keys():
                    return False, f"Unable to find interface with name '{self.settings.interface}'"


            self.outfile = Path("/") / Path(self.settings.filename)
            if self.outfile.exists():
                return False, f"Cannot override existing file '{self.outfile}'"

            return True, None
        except Exception as ex:
            return False, f"Config validation failed: {ex}"

    def start(self, runtime: Optional[int]) -> bool:
        if self.settings is None:
            return False
        
        if runtime is None:
            return False
        
        command = ["/usr/bin/tcpdump", "-i", self.settings.interface, 
                   "-G", str(runtime), "-W", "1", "-w", str(self.outfile)]
        
        if self.settings.filter is not None:
            command.append(f"'{self.settings.filter}'")
        
        try:
            process = subprocess.Popen(command, shell=False, 
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception as ex:
            raise Exception(f"Unable to run tcpdump: {ex}")

        try:
            status = process.wait(runtime + 1)
            failed = status != 0

            if failed and process.stdout is not None:
                for line in process.stdout.readlines():
                    if line is None or line == b"":
                        continue
                    self.interface.push_log_message(line.decode('utf-8').replace('\n', ''), 
                                                    LogMessageType.STDOUT, True)

            if failed and process.stderr is not None:
                for line in process.stderr.readlines():
                    if line is None or line == b"":
                        continue
                    self.interface.push_log_message(line.decode('utf-8').replace('\n', ''), 
                                                    LogMessageType.STDERR, True)

            if failed:
                self.interface.push_log_message(f"tcpdump exited with unexpected status {status}.", 
                                                LogMessageType.MSG_ERROR, True)
                return False
            elif not self.interface.preserve_file(str(self.outfile)):
                self.interface.push_log_message(f"Unable to preserve tcpdump outfile '{self.outfile}'", 
                                                LogMessageType.MSG_ERROR, True)
                return False

            return True
        except subprocess.TimeoutExpired as ex:
            process.kill()
            self.interface.push_log_message(f"Timeout during tcpdump execution: {ex}", 
                                            LogMessageType.MSG_ERROR, True)
            return False
            
    def exports_data(self) -> bool:
        return False
