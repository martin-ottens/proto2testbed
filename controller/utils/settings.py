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

import os
import json
import re

from typing import List, Dict, Optional, Any
from enum import Enum
from abc import ABC
from dataclasses import dataclass
from loguru import logger

from common.application_configs import ApplicationConfig


@dataclass
class TestbedSettings:
    management_network: Optional[str] = None
    diskimage_basepath: str = "./"
    startup_init_timeout: int = 30 # seconds
    experiment_timeout: int = -1 # seconds
    file_preservation_timeout: int = 30 # seconds
    checkpoint_timeout: int = 30 # seconds
    appstart_timesync_offset: int = 1 # seconds
    allow_gso_gro: bool = False


@dataclass
class TestbedNetwork:
    name: str
    host_ports: List[str] = None


class IntegrationSettings(ABC):
    pass
    

class InvokeIntegrationAfter(Enum):
    STARTUP = "startup"
    NETWORK = "network"
    INIT = "init"

    def __str__(self) -> str:
        return str(self.value)
    

class Integration:
    def __init__(self, name: str, type: str, environment: Optional[Dict[str, str]] = None,
                 invoke_after: str = str(InvokeIntegrationAfter.STARTUP), wait_after_invoke: int = 0,
                 settings: Optional[Any] = None) -> None:

        self.name = name
        self.type = type
        self.environment = environment
        self.invoke_after: InvokeIntegrationAfter = InvokeIntegrationAfter(invoke_after)
        self.wait_after_invoke = wait_after_invoke
        self.settings: IntegrationSettings = settings

    def __str__(self) -> str:
        return f"{self.name} ({self.type})"


class AttachedNetwork:
    def __init__(self, name: str, mac: Optional[str] = None, 
                 netmodel: str = "virtio", vhost: bool = True) -> None:
        self.name: str = name
        self.mac: Optional[str] = mac
        self.netmodel: str = netmodel
        self.vhost: bool = vhost

        if self.mac is not None:
            if re.fullmatch(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$', self.mac) is None:
                raise Exception(f"MAC address '{self.mac}' (attached to network {name}) is invalid!")

    def __str__(self) -> str:
        return self.name


class TestbedInstance:
    def __init__(self, name: str, diskimage: str, setup_script: str = None, 
                 environment: Optional[Dict[str, str]] =  None, cores: int = 2, 
                 memory: int = 1024, management_address: Optional[str] = None, 
                 networks: Optional[List[Any]] = None, applications = None, 
                 preserve_files: Optional[List[str]] = None) -> None:

        if "@" in name:
            raise Exception(f"Instance name '{name}' contains the reserved '@' character.")
        
        self.name: str = name
        self.diskimage: str = diskimage
        self.setup_script: str = setup_script
        self.environment: Dict[str, str] = environment
        self.cores: int = cores
        self.memory: int = memory
        self.preserve_files: List[str] = preserve_files
        self.management_address = management_address
        self.networks: List[AttachedNetwork] = []

        self.applications: List[ApplicationConfig] = []
        for network in networks:
            if isinstance(network, str):
                self.networks.append(AttachedNetwork(network, None))
            else:
                self.networks.append(AttachedNetwork(**network))

        if applications is None:
            return

        for application in applications:
            self.applications.append(ApplicationConfig(**application))
    
    def __str__(self) -> str:
        return self.name


class TestbedConfig:
    def __init__(self, json_dict) -> None:
        self.settings: TestbedSettings = TestbedSettings(**json_dict["settings"])
        self.networks: List[TestbedNetwork] = []
        self.instances: List[TestbedInstance] = []
        self.integrations: List[Integration] = []

        for network in json_dict["networks"]:
            self.networks.append(TestbedNetwork(**network))
        
        for integration in json_dict["integrations"]:
            self.integrations.append(Integration(**integration))

        for instance in json_dict["instances"]:
            self.instances.append(TestbedInstance(**instance))


class DefaultConfigs:
    def __init__(self, path: str) -> None:
        self.defaults = {}
        if not os.path.exists(path):
            logger.debug(f"No default config in path '{path}' (or not readable)")
            return
        
        with open(path, "r") as handle:
            self.defaults = json.load(handle)

    def get_defaults(self, key: str, fallback: Any = None):
        if self.defaults is None or key not in self.defaults.keys():
            logger.debug(f"No default value for key '{key}' provided in config.")
            return fallback
        else:
            return self.defaults.get(key)


@dataclass
class RunParameters:
    disable_kvm: bool = False
    dont_use_influx: Optional[bool] = False
    skip_integration: bool = False
    create_checkpoint: bool = False
