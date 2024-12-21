import random
import string

from typing import Optional, List, Dict, Any
from constants import TAP_PREFIX, BRIDGE_PREFIX

from helper.network_helper import NetworkBridge


class BridgeMapping():
    def __init__(self, name: str, dev_name: str) -> None:
        self.name = name
        self.dev_name: str = dev_name
        self.bridge: NetworkBridge = None

    def __str__(self) -> str:
        return f"{self.name} ({self.dev_name})"


class InstanceInterface():
    def __init__(self, tap_index: int, 
                 tap_dev: Optional[str] = None,
                 tap_mac: Optional[str] = None,
                 host_ports: Optional[List[str]] = None,
                 bridge_dev: Optional[str] = None,
                 bridge_name: Optional[str] = None,
                 bridge: Optional[BridgeMapping] = None,
                 is_management_interface: bool = False,
                 instance = None) -> None:
        self.tap_index = tap_index
        self.tap_dev = tap_dev
        self.tap_mac = tap_mac
        self.bridge = bridge
        self.bridge_attached = False
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

    

    def __lt__(self, other) -> bool:
        return self.tap_index < other.tap_index
    
    def dump(self) -> Any:
        return {
            "tap_index": self.tap_index,
            "tap_dev": self.tap_dev,
            "tap_mac": self.tap_mac,
            "host_ports": self.host_ports,
            "bridge_dev": self.bridge_dev,
            "bridge_name": self.bridge_name,
            "is_management_interface": self.is_management_interface
        }


class NetworkMappingHelper():
    def __init__(self) -> None:
        self.bridge_map: Dict[str, BridgeMapping] = {}

    def _generate_name(self) -> str:
        return "".join(random.choices(string.ascii_letters + string.digits, k=8))
    
    def generate_tap_name(self) -> str:
        while True:
            choice = TAP_PREFIX + self._generate_name()
            if NetworkBridge.check_interfaces_available([choice]):
                continue
            
            return choice

    def add_bridge_mapping(self, config_name: str) -> BridgeMapping:
        if config_name in self.bridge_map.keys():
            raise Exception(f"Bridge {config_name} already mapped.")

        while True:
            choice = BRIDGE_PREFIX + self._generate_name()
            if NetworkBridge.check_interfaces_available([choice]):
                continue
            
            mapping = BridgeMapping(config_name, choice)
            self.bridge_map[config_name] = mapping
            return mapping

    def get_bridge_mapping(self, config_name: str) -> Optional[BridgeMapping]:
        return self.bridge_map.get(config_name, None)
