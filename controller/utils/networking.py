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

import random
import string

from typing import Optional, List, Dict, Any
from constants import TAP_PREFIX, BRIDGE_PREFIX

from helper.network_helper import NetworkBridge


class BridgeMapping:
    def __init__(self, name: str, dev_name: str) -> None:
        self.name = name
        self.dev_name: str = dev_name
        self.bridge: NetworkBridge = None

    def __str__(self) -> str:
        return f"{self.name} ({self.dev_name})"


class InstanceInterface:

    _EXPORT_ATTRIBUTES = [
        "tap_index",
        "tap_dev",
        "tap_mac",
        "host_ports",
        "bridge_name",
        "bridge_dev",
        "interface_on_instance",
        "is_management_interface"
    ]

    def __init__(self, tap_index: int, 
                 tap_dev: Optional[str] = None,
                 tap_mac: Optional[str] = None,
                 netmodel: str = "virtio",
                 host_ports: Optional[List[str]] = None,
                 bridge_dev: Optional[str] = None,
                 bridge_name: Optional[str] = None,
                 bridge: Optional[BridgeMapping] = None,
                 is_management_interface: bool = False,
                 interface_on_instance: Optional[str] = None,
                 instance = None) -> None:
        self.tap_index = tap_index
        self.tap_dev = tap_dev
        self.tap_mac = tap_mac
        self.netmodel = netmodel
        self.bridge = bridge
        self.bridge_attached = False
        self.interface_on_instance = interface_on_instance
        self.is_management_interface = is_management_interface
        self.instance = instance

        if bridge is not None:
            self.bridge_name = bridge.name
            self.bridge_dev = bridge.dev_name
            self.host_ports = bridge.bridge.host_ports
        else:
            self.bridge_name = bridge_name
            self.bridge_dev = bridge_dev
            self.host_ports = host_ports

    def check_export_values(self) -> Optional[str]:
        for attr in InstanceInterface._EXPORT_ATTRIBUTES:
            if getattr(self, attr) is None:
                return f"Attribute {attr} is not set!"
        
        return None

    def __lt__(self, other) -> bool:
        return self.tap_index < other.tap_index
    
    def __getstate__(self):
        state = self.__dict__.copy()
        delkeys = []
        for val in state.keys():
            if val not in InstanceInterface._EXPORT_ATTRIBUTES:
                delkeys.append(val)

        for attr in delkeys:
            del state[attr]

        return state

    def __setstate__(self, state):
        self.__dict__.update(state)


class NetworkMappingHelper:
    def __init__(self) -> None:
        self.bridge_map: Dict[str, BridgeMapping] = {}

    def _generate_name(self) -> str:
        return "".join(random.choices(string.ascii_letters + string.digits, k=8))
    
    def generate_tap_name(self) -> str:
        tries = 0
        while True:
            choice = TAP_PREFIX + self._generate_name()
            if NetworkBridge.check_interfaces_available([choice]):
                if tries > 100:
                    raise Exception("Unable to generate TAP name")

                tries += 1
                continue
            
            return choice

    def add_bridge_mapping(self, config_name: str) -> BridgeMapping:
        if config_name in self.bridge_map.keys():
            raise Exception(f"Bridge {config_name} already mapped.")

        tries = 0
        while True:
            choice = BRIDGE_PREFIX + self._generate_name()
            if NetworkBridge.check_interfaces_available([choice]):
                if tries > 100:
                    raise Exception("Unable to generate BRIDGE name")

                tries += 1
                continue
            
            mapping = BridgeMapping(config_name, choice)
            self.bridge_map[config_name] = mapping
            return mapping

    def get_bridge_mapping(self, config_name: str) -> Optional[BridgeMapping]:
        return self.bridge_map.get(config_name, None)
