import json
import ipaddress
import time

from loguru import logger
from typing import List

from helper.network_helper import NetworkBridge
from helper.vm_helper import VMWrapper
from utils.interfaces import Dismantable

class Controller(Dismantable):
    def __init__(self, config_path):
        with open(config_path, "r") as handle:
            self.config = json.load(handle)
        
        self.dismantables: List[Dismantable] = []
    
    def _destory(self) -> None:
        for dismantable in self.dismantables:
            try:
                dismantable.dismantle()
            except Exception as ex:
                logger.opt(exception=ex).error(f"Unable to dismantle {dismantable.get_name()}")

    def __del__(self):
        self._destory()

    def dismantle(self) -> None:
        self._destory()
    
    def get_name(self) -> str:
        return f"Controller"

    def setup_infrastructure(self) -> bool:
        mgmt_network = ipaddress.IPv4Network(self.config["settings"]["management_network"])
        mgmt_ips = list(mgmt_network.hosts())
        mgmt_netmask = ipaddress.IPv4Network(f"0.0.0.0/{mgmt_network.netmask}").prefixlen

        # Setup Networks
        networks = {}

        try:
            mgmt_bridge = NetworkBridge("br-mgmt")
            self.dismantables.insert(0, mgmt_bridge)
            mgmt_gateway = mgmt_ips.pop(0)
            mgmt_bridge.setup_local(ip=ipaddress.IPv4Interface(f"{mgmt_gateway}/{mgmt_netmask}"), 
                                    nat=mgmt_network if self.config["settings"]["machines_internet_access"] == True else None)
            mgmt_bridge.start_bridge()
            networks["br-mgmt"] = mgmt_bridge
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to setup management network!")
            return False

        for network in self.config["networks"]:
            try:
                bridge = NetworkBridge(network["name"])
                self.dismantables.insert(0, bridge)
                for pyhsical_port in network["physical_ports"]:
                    bridge.add_device(pyhsical_port)
                bridge.start_bridge()
                networks[network["name"]] = bridge
            except Exception as ex:
                logger.opt(exception=ex).critical(f"Unable to setup additional network {network['name']}")
                return False
            
        # Setup VMs
        machines = {}
        wait_for_interfaces = ["br-mgmt"]
        for index, machine in enumerate(self.config["machines"]):
            extra_interfaces = {}

            for if_index, if_bridge in enumerate(machine["networks"]):
                if_int_name = f"v_{index}_{if_index}"
                extra_interfaces[if_int_name] = if_bridge
                wait_for_interfaces.append(if_int_name)

            try:
                wrapper = VMWrapper(name=machine["name"],
                                    management={
                                        "interface": f"v_{index}_m",
                                        "ip": ipaddress.IPv4Interface(f"{mgmt_ips.pop(0)}/{mgmt_netmask}"),
                                        "gateway": str(mgmt_gateway)
                                    },
                                    extra_interfaces=extra_interfaces.keys(),
                                    image=machine["diskimage"],
                                    cores=machine["cores"],
                                    memory=machine["memory"])
                self.dismantables.insert(0, wrapper)
                wrapper.start_instance()
                extra_interfaces[f"v_{index}_m"] = "br-mgmt"
                machines[machine["name"]] = (wrapper, extra_interfaces, )
            except Exception as ex:
                logger.opt(exception=ex).critical(f"Unable to setup and start VM {machine['name']}")
        
        # Wait for tap devices to become ready
        wait_until = time.time() * 20
        while True:
            if NetworkBridge.check_interfaces_available(extra_interfaces):
                break

            if time.time() > wait_until:
                logger.critical("VM Interfaces are not ready after 20 seconds!")
                return False

            time.sleep(1)

        # Attach tap devices to bridges
        try:
            for name, machine in machines.items():
                wrapper, extra_interfaces = machine
                for interface, bridge in extra_interfaces.items():
                    networks[bridge].add_device(interface)
                logger.info(f"{name} ({wrapper.ip_address}) attached to bridges: {', '.join(extra_interfaces.values())}")
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to attach VM interfaces to bridges.")
            return False

        return True
        
    def main(self):
        if not self.setup_infrastructure():
            logger.critical("Critical error during setup, dismantling!")
            self.dismantle()

        wait_seconds = self.config["settings"]["auto_dismantle_seconds"]
        logger.success(f"Testbed is ready, CRTL+C to dismantle (Auto stop after {wait_seconds}s)")

        try: 
            time.sleep(wait_seconds)
        except KeyboardInterrupt:
            logger.info("Starting dismantle!")

        self.dismantle()
        
        logger.success("Testbed was dismantled!")









