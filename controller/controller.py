from helper.network_helper import NetworkBridge
from helper.vm_helper import VMWrapper

from loguru import logger

import json
import ipaddress
import time

class Controller:
    def __init__(self, config_path):
        with open(config_path, "r") as handle:
            config = json.load(handle)

        mgmt_network = ipaddress.IPv4Network(config["settings"]["management_network"])
        mgmt_ips = list(mgmt_network.hosts())
        mgmt_netmask = ipaddress.IPv4Network(f"0.0.0.0/{mgmt_network.netmask}").prefixlen

        # Setup Networks
        networks = {}
        mgmt_bridge = NetworkBridge("br-mgmt")
        mgmt_gateway = mgmt_ips.pop(0)
        mgmt_bridge.setup_local(ip=ipaddress.IPv4Interface(f"{mgmt_gateway}/{mgmt_netmask}"), 
                                nat=mgmt_network if config["settings"]["machines_internet_access"] == True else None)
        mgmt_bridge.start_bridge()
        networks["br-mgmt"] = mgmt_bridge

        for network in config["networks"]:
            bridge = NetworkBridge(network["name"])
            for pyhsical_port in network["physical_ports"]:
                bridge.add_device(pyhsical_port)
            bridge.start_bridge()
            networks[network["name"]] = bridge

        # Setup VMs
        machines = {}
        for index, machine in enumerate(config["machines"]):
            extra_interfaces = {}

            for if_index, if_bridge in enumerate(machine["networks"]):
                if_int_name = f"v_{index}_{if_index}"
                extra_interfaces[if_int_name] = if_bridge

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
            wrapper.start_instance()
            extra_interfaces[f"v_{index}_m"] = "br-mgmt"
            machines[machine["name"]] = (wrapper, extra_interfaces, )
        
        time.sleep(len(machines))

        for name, machine in machines.items():
            wrapper, extra_interfaces = machine
            for interface, bridge in extra_interfaces.items():
                networks[bridge].add_device(interface)
            logger.info(f"{name} ({wrapper.ip_address}) attached to bridges: {', '.join(extra_interfaces.values())}")

        logger.success("Testbed is ready, CRTL+C to dismantle!")
        
        try:
            time.sleep(config["settings"]["auto_dismantle_seconds"])
        except KeyboardInterrupt:
            logger.critical("Starting dismantle!")

        for machine in machines.values():
            wrapper, _ = machine
            wrapper.stop_instance()
        
        time.sleep(5)

        for network in networks.values():
            network.stop_bridge()
        
        logger.success("Testbed was dismantled!")










