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

import json

from typing import Dict, Optional, List, Tuple
from multiprocessing import Process
from loguru import logger
from dataclasses import dataclass

from utils.settings import IntegrationSettings
from utils.system_commands import invoke_subprocess
from base_integration import BaseIntegration, IntegrationStatusContainer


@dataclass
class NS3IntegrationSettings(IntegrationSettings):
    basepath: str
    program: str
    interfaces: List[str]
    wait: bool = False
    fail_on_exist: bool = False
    args: Optional[Dict[str, str]] = None


class NS3Integration(BaseIntegration):
    NAME = "ns3-emulation"

    def __init__(self, name: str, status_container: IntegrationStatusContainer, 
                 environment: Optional[Dict[str, str]] = None) -> None:
        super().__init__(name, status_container, environment)
        self.process = None
        self.settings = None

    def set_and_validate_config(self, config: IntegrationSettings) -> Tuple[bool, Optional[str]]:
        try:
            self.settings = NS3IntegrationSettings(**config)
            return True, None
        except Exception as ex:
            return False, f"Config validation failed: {ex}"

    def is_integration_blocking(self) -> bool:
        return False
    
    def get_expected_timeout(self, at_shutdown: bool = False) -> int:
        return 300 if at_shutdown else 0

    def start(self) -> bool:
        # 0. Search for existing interfaces
        sub_process = invoke_subprocess(["/usr/sbin/ip", "--json", "--details", "link", "show"])
        if sub_process.returncode != 0:
            self.status.set_error(f"Unable to check for existing interfaces: {sub_process.stderr.decode('utf-8')}")
            return False
        
        interface_list = json.loads(sub_process.stdout.decode("utf-8"))
        for interface in interface_list:
            if interface["ifname"] in self.settings.interfaces:
                if self.settings.fail_on_exist:
                    self.status.set_error(f"Interface '{interface['ifname']}' already exists.")
                    return False
                
                if interface["linkinfo"]["type"] != "tap":
                    self.status.set_error(f"Interface with name '{interface['ifname']}' already exists, but its not tap.")
                    return False
                
                # Not managed by us, so don't touch.
                logger.warning(f"ns-3 Integration {self.name}: Ignoring existing interface {interface['ifname']}")
                self.settings.interfaces.remove(interface["ifname"])

        # 1. Create new interfaces
        for interface in self.settings.interfaces:
            try:
                sub_process = invoke_subprocess(["/usr/sbin/ip", "tuntap", "add", interface, "mode", "tap"])
                if sub_process.returncode != 0:
                    self.status.set_error(f"Unable to create tap interface '{interface}': {sub_process.stderr.decode('utf-8')}")
                    return False
                
                sub_process = invoke_subprocess(["/usr/sbin/ip", "link", "set", "up", "dev", interface])
                if sub_process.returncode != 0:
                    self.status.set_error(f"Unable to set link '{interface}' up: {sub_process.stderr.decode('utf-8')}")
                    return False
            except Exception as ex:
                self.status.set_error(f"Unable to configure tap interface '{interface}': {ex}")
                return False

        # 2. Start ns-3
        ns_3_command = f"cd {self.settings.basepath} && ./ns3 run {self.settings.program} --no-build"
        if self.settings.args is not None and len(self.settings.args) > 0:
            ns_3_command += " -- "
            for k, v in self.settings.args.items():
                ns_3_command += f"--{k}={v}"

        self.process = Process(target=self.run_subprocess, args=(ns_3_command, True, None, ))
        self.process.start()
        return True

    def stop(self) -> bool:
        try:
            if self.process is not None and self.process.is_alive():
                if self.settings.wait:
                    logger.info(f"ns-3 Integration {self.name}: Waiting for ns-3 process '{self.name}' to terminate")
                    self.process.join()
                else:
                    logger.info(f"ns-3 Integration {self.name}: Killing ns-3 process '{self.name}' without waiting")
                    self.kill_process_with_child(self.process)
        except Exception as ex:
            self.status.set_error(f"Error during stop of ns-3 process '{self.name}' - skipping interface deletion: {ex}")
            return False
        
        got_error = False
        for interface in self.settings.interfaces:
            try:
                sub_process = invoke_subprocess(["/usr/sbin/ip", "link", "del", interface])
                if sub_process.returncode != 0:
                    logger.error(f"ns-3 Integration {self.name}: Unable to delete tap interface '{interface}': {sub_process.stderr.decode('utf-8')}")
                    got_error = True

            except Exception as ex:
                logger.opt(exception=ex).error(f"ns-3 Integration {self.name}: Error deleting tap interface '{interface}'")
                got_error = True

        if got_error:
            self.status.set_error(f"At least one tap interface could not be deleted!")
            return False
        else:
            return True
