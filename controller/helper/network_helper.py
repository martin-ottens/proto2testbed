import ipaddress
import subprocess
import json
import time
import sys

from typing import List
from loguru import logger


class NetworkBridge():
    def _run_command(self, command: List[str]):
        logger.trace("Running command:" + " ".join(command))
        process = subprocess.run(command, shell=False, capture_output=True)
        if process.returncode != 0:
            logger.error(f"Network {self.name}: Command '{' '. join(command)}' failed: {process.stderr.decode('utf-8')}")
            return False

        return True
        
    def __init__(self, name: str):
        self.name = name
        self.dismantle_action = []
        self.ready = False

        if len(name) > 8:
            logger.error(f"Network {self.name}: Bridge Interface name is too long!")
            return

        if not self._run_command(["/usr/sbin/brctl", "addbr", self.name]):
            logger.error(f"Network {self.name}: Setup failed!")
            return
        self.dismantle_action.insert(0, ["/usr/sbin/brctl", "delbr", self.name])

        logger.info(f"Network {self.name}: Bridge ready!")
        self.ready = True

    def __del__(self):
        self.stop_bridge()
    
    def start_bridge(self):
        if not self._run_command(["/usr/sbin/ip", "link", "set", "up", "dev", self.name]):
            logger.error(f"Network {self.name}: Startup failed!")
            return
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

        process = subprocess.run(["/usr/sbin/ip", "-j", "link", "show"], 
                                 capture_output=True, shell=False)
        if process.returncode != 0:
            logger.error(f"Network {self.name}: Unable to check interface {interface}: {process.stderr.decode('utf-8')}")
            return False
        
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
                    logger.error(f"Network {self.name}: Unable to remove {interface} from bridge {check_if_master}!")
                    return False
            
        if not was_found:
            logger.error(f"Network {self.name}: Interface {interface} was not found!")
            return False

        if not self._run_command(["/usr/sbin/brctl", "addif", self.name, interface]):
            logger.error(f"Network {self.name}: Unable to add {interface} to bridge!")
            return False
        if undo:
            self.dismantle_action.insert(0, ["/usr/sbin/brctl", "delif", self.name, interface])
        return True

    def setup_local(self, ip: ipaddress.IPv4Interface, nat: ipaddress.IPv4Network | None = None):
        logger.debug(f"Network {self.name}: Adding IP {str(ip)} to bridge.")
        if not self._run_command(["/usr/sbin/ip", "addr", "add", str(ip), "dev", self.name]):
            logger.error(f"Network {self.name}: Unable to add IP {str(ip)} to bridge!")
            return False

        if nat is None:
            return True

        logger.info(f"Network {self.name}: NAT: Enabling NAT for {str(nat)}!")

        # Get default prefsrc
        process = subprocess.run(["/usr/sbin/ip", "-j", "route"], 
                                 capture_output=True, shell=False)
        if process.returncode != 0:
            logger.error(f"Network {self.name}: NAT: Unable to check default route: {process.stderr.decode('utf-8')}")
            return False

        route_list = json.loads(process.stdout.decode("utf-8"))

        default_route_device = None
        for route in route_list:
            if not "dst" in route or not "dev" in route:
                continue

            if route["dst"] == "default":
                default_route_device = route["dev"]
                break

        if default_route_device is None:
            logger.error(f"Network {self.name}: NAT: Unable to obtain default route!")
            return False
        
        default_route_prefsrc = None
        for route in route_list:
            if not "dst" in route or not "dev" in route or not "prefsrc" in route:
                continue
            
            if route["dst"] != "default" and route["dev"] == default_route_device:
                default_route_prefsrc = route["prefsrc"]
                break
        
        if default_route_prefsrc is None:
            logger.error(f"Network {self.name}: NAT: Unable to obtain default route!")
            return False

        if not self._run_command(["/usr/sbin/sysctl", "-w", "net.ipv4.conf.all.forwarding=1"]):
            logger.error(f"Network {self.name}: NAT: Unable to allow IPv4 forwarding on host!")
            return False

        if not self._run_command(["/usr/sbin/iptables", "-A", "FORWARD", "-s", str(nat), "-j", "ACCEPT"]):
            logger.error(f"Network {self.name}: NAT: Unable to create iptables rule!")
            return False
        self.dismantle_action.insert(0, ["/usr/sbin/iptables", "-D", "FORWARD", "-s", str(nat), "-j", "ACCEPT"])

        if not self._run_command(["/usr/sbin/iptables", "-A", "FORWARD", "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"]):
            logger.error(f"Network {self.name}: NAT: Unable to create iptables rule!")
            return False
        self.dismantle_action.insert(0, ["/usr/sbin/iptables", "-D", "FORWARD", "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"])

        if not self._run_command(["/usr/sbin/iptables", "-t", "nat", "-A", "POSTROUTING", "-s", str(nat), "-j", "SNAT", "--to-source", default_route_prefsrc]):
            logger.error(f"Network {self.name}: NAT: Unable to create iptables rule!")
            return False
        self.dismantle_action.insert(0, ["/usr/sbin/iptables", "-t", "nat", "-D", "POSTROUTING", "-s", str(nat), "-j", "SNAT", "--to-source", default_route_prefsrc])

        return True
