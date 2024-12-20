from dataclasses import dataclass
from typing import Optional, List

@dataclass
class InstanceInterface():
    tap_index: int
    bridge_dev: Optional[str] = None
    bridge_name: Optional[str] = None
    tap_dev: Optional[str] = None
    tap_mac: Optional[str] = None
    host_ports: Optional[List[str]] = None
    instance = None
    bridge = None
    bridge_attached: bool = False
    is_management_interface: bool = False

    def __lt__(self, other) -> bool:
        return self.tap_index < other.tap_index
    