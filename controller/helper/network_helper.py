import ipaddress
import json
import random
import string
import ipaddress
import psutil
import socket

from typing import Dict, List, Optional
from loguru import logger

from utils.interfaces import Dismantable
from utils.system_commands import invoke_subprocess
from utils.settings import CommonSettings
from constants import TAP_PREFIX, BRIDGE_PREFIX

class NetworkBridge(Dismantable):

    @staticmethod
    def get_running_interfaces() -> List[str]:
        process = invoke_subprocess(["/usr/sbin/ip", "--brief", "--json", "link", "show"])
        if process.returncode != 0:
            raise Exception(f"Unable to fetch interfaces: {process.stderr}")
        
        return list(map(lambda x: x["ifname"], json.loads(process.stdout.decode("utf-8"))))

    @staticmethod
    def cleanup_interface(if_name: str, fail_silent: bool = False) -> bool:
        if if_name.startswith(BRIDGE_PREFIX):
            process = invoke_subprocess(["/usr/sbin/ip", "link", "set", "down", "dev", if_name], 
                                        needs_root=True)
            if process.returncode != 0:
                logger.error(f"Unable to set bridge '{if_name}' down: {process.stderr.decode('utf-8')}")
                return False

            process = invoke_subprocess(["/usr/sbin/brctl", "delbr", if_name], 
                                        needs_root=True)
            if process.returncode != 0:
                logger.error(f"Unable to delete bridge '{if_name}': {process.stderr.decode('utf-8')}")
                return False

            return True
        elif if_name.startswith(TAP_PREFIX):
            process = invoke_subprocess(["/usr/sbin/ip", "link", "set", "down", "dev", if_name], 
                                        needs_root=True)
            if process.returncode != 0:
                logger.error(f"Unable to set tap device '{if_name}' down: {process.stderr.decode('utf-8')}")
                return False

            process = invoke_subprocess(["/usr/sbin/ip", "link", "del", "dev", if_name], 
                                        needs_root=True)
            if process.returncode != 0:
                logger.error(f"Unable to delete tap device '{if_name}': {process.stderr.decode('utf-8')}")
                return False

            return True
        elif not fail_silent:
            logger.error(f"Interface '{if_name}' is not managed by the testbed system. Unable to delete.")

        return False

    @staticmethod
    def check_interfaces_available(interfaces: List[str]):
        return all(x in NetworkBridge.get_running_interfaces() for x in interfaces)
    
    @staticmethod
    def generate_auto_management_network(seed: str) -> Optional[ipaddress.IPv4Network]:
        random.seed(seed)

        supernet = ipaddress.ip_network(CommonSettings.default_configs.get_defaults("management_network"))
        possible_subnets = list(supernet.subnets(new_prefix=26))

        tries_left = 10
        while True:
            if tries_left <= 0:
                return None

            subnet = random.choice(possible_subnets)
            if NetworkBridge.is_network_in_use(subnet):
                tries_left -= 1
                continue

            return subnet
        
    @staticmethod
    def is_network_in_use(network: ipaddress.IPv4Network) -> bool:
        for iface, addresses in psutil.net_if_addrs().items():
            for address in addresses:
                if address.family != socket.AF_INET:
                    continue

                test_ip = ipaddress.ip_address(address.address)

                if test_ip in network:
                    logger.debug(f"IP '{test_ip}' from network '{network}' is already in use on interface '{iface}'")
                    return True

        return False

    def _run_command(self, command: List[str]):
        process = invoke_subprocess(command, needs_root=True)
        if process.returncode != 0:
            logger.error(f"Network {self.name}: Command '{' '. join(command)}' failed: {process.stderr.decode('utf-8')}")
            return False

        return True
        
    def __init__(self, name: str, display_name: str):
        self.name = name
        self.display_name = display_name
        self.dismantle_action = []
        self.ready = False
        self.host_ports: List[str] = []

        if len(name) >= 16: # IFNAMSIZ = 16 including NULL termination
            raise Exception(f"Bridge interface name '{self.name}' is too long!")
        
        is_running =  NetworkBridge.check_interfaces_available([name])

        if is_running:
            logger.warning(f"Bridge {self.name} exists, skipping creation (Concurrent testbeds?)")
        else:
            if not self._run_command(["/usr/sbin/brctl", "addbr", self.name]):
                raise Exception(f"Setup of bridge '{self.name}' (for '{self.display_name}') failed")

            self.dismantle_action.insert(0, ["/usr/sbin/brctl", "delbr", self.name])

        logger.info(f"Network {self.display_name}: Bridge ready!")
        self.ready = True

    def __str__(self):
        return f"{self.display_name}"

    def __del__(self):
        self.stop_bridge()

    def dismantle(self, force: bool = False):
        self.stop_bridge()

    def get_name(self) -> str:
        return f"NetworkBridge {self.name} ({self.display_name})"
    
    def start_bridge(self):
        if not self._run_command(["/usr/sbin/ip", "link", "set", "up", "dev", self.name]):
            raise Exception(f"Unable to bring bridge '{self.name}' (for '{self.display_name}') up")
        self.dismantle_action.insert(0, ["/usr/sbin/ip", "link", "set", "down", "dev", self.name])

    def stop_bridge(self):
        if not self.ready or len(self.dismantle_action) == 0:
            return False

        logger.info(f"Network '{self.display_name}': Stopping bridge.")

        status = True
        while len(self.dismantle_action) > 0:
            action = self.dismantle_action.pop(0)
            if not self._run_command(action):
                logger.warning(f"Network '{self.name}' (for '{self.display_name}'): Error executing dismantle command!")
                status = False
        
        return status

    def add_device(self, interface: str, undo: bool = False, is_host_port: bool = False) -> bool:
        logger.debug(f"Network '{self.name}' (for '{self.display_name}'): Adding interface {interface} to bridge.")

        process = invoke_subprocess(["/usr/sbin/ip", "--json", "link", "show"])
        if process.returncode != 0:
            raise Exception(f"Unable to check interface {interface}: {process.stderr.decode('utf-8')}")
        
        interface_list = json.loads(process.stdout.decode("utf-8"))
        was_found = False
        for check_interface in interface_list:
            if check_interface["ifname"] != interface:
                continue

            was_found = True

            if not "master" in check_interface:
                break

            check_if_master = check_interface["master"]
            if check_if_master == self.name:
                logger.debug(f"Network '{self.name}' (for '{self.display_name}'): Interface {interface} was already added to this bridge.")
                return True
            else:
                logger.debug(f"Network '{self.name}' (for '{self.display_name}'): Interface {interface} is currently added to brigde {check_if_master}, removing ...")
                if not self._run_command(["/usr/sbin/brctl", "delif", check_if_master, interface]):
                    raise Exception(f"Unable to remove {interface} from bridge {check_if_master}!")
            
        if not was_found:
            raise Exception(f"Interface {interface} was not found!")

        if not self._run_command(["/usr/sbin/brctl", "addif", self.name, interface]):
            logger.error(f"Unable to add {interface} to bridge {self.name}.")
        if undo:
            self.dismantle_action.insert(0, ["/usr/sbin/brctl", "delif", self.name, interface])

        if is_host_port:
            self.host_ports.append(interface)
        
        return True

    def setup_local(self, ip: ipaddress.IPv4Interface, nat: ipaddress.IPv4Network) -> bool:
        logger.debug(f"Network '{self.name}' (for '{self.display_name}'): Adding IP {str(ip)} to bridge.")
        if not self._run_command(["/usr/sbin/ip", "addr", "add", str(ip), "dev", self.name]):
            raise Exception(f"Unable to add IP {str(ip)} to bridge '{self.name}' (for '{self.display_name}')!")

        logger.info(f"Network '{self.display_name}': NAT: Enabling NAT for {str(nat)}!")

        # Get default prefsrc
        process = invoke_subprocess(["/usr/sbin/ip", "--json", "route"])
        if process.returncode != 0:
            raise Exception(f"NAT: Unable to check default route: {process.stderr.decode('utf-8')}")

        route_list = json.loads(process.stdout.decode("utf-8"))

        default_route_device = None
        for route in route_list:
            if not "dst" in route or not "dev" in route:
                continue

            if route["dst"] == "default":
                default_route_device = route["dev"]
                break

        if default_route_device is None:
            raise Exception(f"NAT: Unable to obtain default route!")
        
        default_route_prefsrc = None
        for route in route_list:
            if not "dst" in route or not "dev" in route or not "prefsrc" in route:
                continue
            
            if route["dst"] != "default" and route["dev"] == default_route_device:
                default_route_prefsrc = route["prefsrc"]
                break
        
        if default_route_prefsrc is None:
            raise Exception(f"NAT: Unable to obtain default route!")

        if not self._run_command(["/usr/sbin/sysctl", "-w", "net.ipv4.conf.all.forwarding=1"]):
            raise Exception(f"NAT: Unable to allow IPv4 forwarding on host!")

        if not self._run_command(["/usr/sbin/iptables", "-A", "FORWARD", "-s", str(nat), "-j", "ACCEPT"]):
            raise Exception(f"NAT: Unable to create iptables rule!")
        self.dismantle_action.insert(0, ["/usr/sbin/iptables", "-D", "FORWARD", "-s", str(nat), "-j", "ACCEPT"])

        if not self._run_command(["/usr/sbin/iptables", "-A", "FORWARD", "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"]):
            raise Exception(f"Unable to create iptables rule!")
        self.dismantle_action.insert(0, ["/usr/sbin/iptables", "-D", "FORWARD", "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"])

        if not self._run_command(["/usr/sbin/iptables", "-t", "nat", "-A", "POSTROUTING", "-s", str(nat), "-j", "SNAT", "--to-source", default_route_prefsrc]):
            raise Exception(f"NAT: Unable to create iptables rule!")
        self.dismantle_action.insert(0, ["/usr/sbin/iptables", "-t", "nat", "-D", "POSTROUTING", "-s", str(nat), "-j", "SNAT", "--to-source", default_route_prefsrc])

        return True


class BridgeMapping():
    def __init__(self, name: str, dev_name: str) -> None:
        self.name = name
        self.dev_name: str = dev_name
        self.bridge: NetworkBridge = None

    def __str__(self) -> str:
        return f"{self.name} ({self.dev_name})"


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
