from helper.network_helper import NetworkBridge
from helper.vm_helper import VMWrapper

from loguru import logger

import json
import ipaddress

class Controller:
    def __init__(self, config_path):
        with open(config_path, "r") as handle:
            config = json.load(handle)

        mgmt_network = ipaddress.IPv4Network(config["settings"]["management_network"])
        mgmt_ips = list(mgmt_network.hosts())

        # Setup Networks
        networks = {}
        mgmt_bridge = NetworkBridge("br-mgmt")
        mgmt_gateway = mgmt_ips.pop()
        mgmt_bridge.setup_local(ip=mgmt_gateway, 
                                netmask=ipaddress.IPv4Network(f"0.0.0.0/{mgmt_network.netmask}").prefixlen,
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

            for if_index, if_bridge in enumerate(machine["extra_interfaces"]):
                if_int_name = f"v_{index}_{if_index}"
                extra_interfaces[if_int_name] = if_bridge

            wrapper = VMWrapper(name=machine["name"],
                                management={
                                    "interface": "br-mgmt",
                                    "ip": str(mgmt_ips.pop()),
                                    "gateway": str(mgmt_gateway),
                                    "netmask": mgmt_network.netmask
                                },
                                extra_interfaces=extra_interfaces.keys(),
                                image=machine["diskimage"],
                                cores=machine["cores"],
                                memory=machine["memory"])








