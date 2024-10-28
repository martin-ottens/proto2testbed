import ipaddress
import json

from typing import List
from loguru import logger

from utils.interfaces import Dismantable
from utils.system_commands import invoke_subprocess

class NetworkBridge(Dismantable):
    @staticmethod
    def check_interfaces_available(interfaces: List[str]):
        process = invoke_subprocess(["/usr/sbin/ip", "--brief", "--json", "link", "show"])
        if process.returncode != 0:
            raise Exception(f"Unable to fetch interfaces: {process.stderr}")
        
        json_interfaces = list(map(lambda x: x["ifname"], json.loads(process.stdout.decode("utf-8"))))

        return all(x in json_interfaces for x in interfaces)


    def _run_command(self, command: List[str]):
        process = invoke_subprocess(command, needs_root=True)
        if process.returncode != 0:
            logger.error(f"Network {self.name}: Command '{' '. join(command)}' failed: {process.stderr.decode('utf-8')}")
            return False

        return True
        
    def __init__(self, name: str, clean: bool = False):
        self.name = name
        self.dismantle_action = []
        self.ready = False

        if len(name) > 8:
            raise Exception(f"Bridge interface name {self.name} is too long!")
        
        is_running =  NetworkBridge.check_interfaces_available([name])

        if is_running and clean:
            logger.warning(f"Bridge {self.name} exists, --clean is set, so deleting bridge.")
            
            if not self._run_command(["/usr/sbin/ip", "link", "set", "down", "dev", self.name]):
                raise Exception(f"Unable to bring bridge {self.name} down")

            if not self._run_command(["/usr/sbin/brctl", "delbr", self.name]):
                raise Exception(f"Deletion of bridge {self.name} failed")
            
            is_running = False

        if is_running:
            logger.warning(f"Bridge {self.name} exists, skipping creation (Concurrent testbeds?)")
        else:
            if not self._run_command(["/usr/sbin/brctl", "addbr", self.name]):
                raise Exception(f"Setup of bridge {self.name} failed")

            self.dismantle_action.insert(0, ["/usr/sbin/brctl", "delbr", self.name])

        logger.info(f"Network {self.name}: Bridge ready!")
        self.ready = True

    def __del__(self):
        self.stop_bridge()

    def dismantle(self):
        self.stop_bridge()

    def get_name(self) -> str:
        return f"NetworkBridge {self.name}"
    
    def start_bridge(self):
        if not self._run_command(["/usr/sbin/ip", "link", "set", "up", "dev", self.name]):
            raise Exception(f"Unable to bring bridge {self.name} up")
        self.dismantle_action.insert(0, ["/usr/sbin/ip", "link", "set", "down", "dev", self.name])

    def stop_bridge(self):
        if not self.ready or len(self.dismantle_action) == 0:
            return False

        logger.info(f"Network {self.name}: Stopping bridge.")

        status = True
        while len(self.dismantle_action) > 0:
            action = self.dismantle_action.pop(0)
            if not self._run_command(action):
                logger.warning(f"Network {self.name}: Error executing dismantle command!")
                status = False
        
        return status

    def add_device(self, interface: str, undo: bool = False) -> bool:
        logger.debug(f"Network {self.name}: Adding interface {interface} to bridge.")

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
                logger.debug(f"Network {self.name}: Interface {interface} was already added to this bridge.")
                return True
            else:
                logger.debug(f"Network {self.name}: Interface {interface} is currently added to brigde {check_if_master}, removing ...")
                if not self._run_command(["/usr/sbin/brctl", "delif", check_if_master, interface]):
                    raise Exception(f"Unable to remove {interface} from bridge {check_if_master}!")
            
        if not was_found:
            raise Exception(f"Interface {interface} was not found!")

        if not self._run_command(["/usr/sbin/brctl", "addif", self.name, interface]):
            logger.error(f"Unable to add {interface} to bridge {self.name}.")
        if undo:
            self.dismantle_action.insert(0, ["/usr/sbin/brctl", "delif", self.name, interface])
        return True

    def setup_local(self, ip: ipaddress.IPv4Interface, nat: ipaddress.IPv4Network) -> bool:
        logger.debug(f"Network {self.name}: Adding IP {str(ip)} to bridge.")
        if not self._run_command(["/usr/sbin/ip", "addr", "add", str(ip), "dev", self.name]):
            raise Exception(f"Unable to add IP {str(ip)} to bridge {self.name}!")

        logger.info(f"Network {self.name}: NAT: Enabling NAT for {str(nat)}!")

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
