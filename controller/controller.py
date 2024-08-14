import ipaddress
import time

from pathlib import Path
from loguru import logger
from typing import List, Tuple
from threading import Event

from helper.network_helper import NetworkBridge
from helper.fileserver_helper import FileServer
from helper.vm_helper import VMWrapper
from helper.integration_helper import IntegrationHelper
from utils.interfaces import Dismantable
from utils.config_tools import load_config, load_vm_initialization, load_influxdb
from utils.settings import SettingsWrapper
from utils.settings import InvokeIntegrationAfter
from management_server import ManagementServer
from state_manager import MachineStateManager, AgentManagementState
from common.instance_manager_message import ExperimentMessageUpstream

FILESERVER_PORT = 4242
MANAGEMENT_SERVER_PORT = 4243

class Controller(Dismantable):
    def __init__(self):
        if SettingsWrapper.cli_paramaters is None:
            raise Exception("No CLIParamaters class object was set before calling the controller")

        self.networks = None
        self.dismantables: List[Dismantable] = []
        self.state_manager: MachineStateManager = MachineStateManager()

        self.base_path = Path(SettingsWrapper.cli_paramaters.config)
        self.config_path = self.base_path / "testbed.json"

        try:
            SettingsWrapper.testbed_config = load_config(self.config_path)
            self.integration_helper = IntegrationHelper(SettingsWrapper.testbed_config.integration, self.base_path)
        except Exception as ex:
            logger.opt(exception=ex).critical("Internal error loading config!")
            raise Exception("Internal config loading error!")
    
    def _destory(self) -> None:
        self.setup_env = None
        self.networks = None
        self.state_manager.remove_all()

        if self.dismantables is None:
            return

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
    
    def setup_local_network(self) -> bool:
        self.mgmt_network = ipaddress.IPv4Network(SettingsWrapper.testbed_config.settings.management_network)
        self.mgmt_ips = list(self.mgmt_network.hosts())
        self.mgmt_netmask = ipaddress.IPv4Network(f"0.0.0.0/{self.mgmt_network.netmask}").prefixlen

        # Setup Networks
        self.networks = {}

        try:
            mgmt_bridge = NetworkBridge("br-mgmt", SettingsWrapper.cli_paramaters.clean)
            self.dismantables.insert(0, mgmt_bridge)
            self.mgmt_gateway = self.mgmt_ips.pop(0)
            mgmt_bridge.setup_local(ip=ipaddress.IPv4Interface(f"{self.mgmt_gateway}/{self.mgmt_netmask}"), 
                                    nat=self.mgmt_network if SettingsWrapper.testbed_config.settings.machines_internet_access == True else None)
            mgmt_bridge.start_bridge()
            self.networks["br-mgmt"] = mgmt_bridge
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to setup management network!")
            return False
        
        return True

    def setup_infrastructure(self) -> bool:
        if self.networks is None:
            logger.critical("Infrastructure setup was called before local network setup!")
            return False

        for network in SettingsWrapper.testbed_config.networks:
            try:
                bridge = NetworkBridge(network.name, SettingsWrapper.cli_paramaters.clean)
                self.dismantables.insert(0, bridge)
                for pyhsical_port in network.physical_ports:
                    bridge.add_device(pyhsical_port)
                bridge.start_bridge()
                self.networks[network.name] = bridge
            except Exception as ex:
                logger.opt(exception=ex).critical(f"Unable to setup additional network {network.name}")
                return False
        
        integration_start = self.integration_helper.handle_stage_start(InvokeIntegrationAfter.NETWORK)
        if integration_start == False :
            logger.critical("Critical error during integration start!")
            return False
        elif integration_start == True:
            self.dismantables.insert(0, self.integration_helper)
            
        # Setup VMs
        machines = {}
        wait_for_interfaces = ["br-mgmt"]
        for index, machine in enumerate(SettingsWrapper.testbed_config.machines):
            extra_interfaces = {}

            for if_index, if_bridge in enumerate(machine.networks):
                if_int_name = f"v_{index}_{if_index}"
                extra_interfaces[if_int_name] = if_bridge
                wait_for_interfaces.append(if_int_name)

            try:
                diskimage_path = Path(machine.diskimage)

                if not diskimage_path.is_absolute():
                    diskimage_path = self.base_path / diskimage_path
                
                if not diskimage_path.exists():
                    raise Exception(f"Unable to find diskimage '{diskimage_path}'")

                wrapper = VMWrapper(name=machine.name,
                                    management={
                                        "interface": f"v_{index}_m",
                                        "ip": ipaddress.IPv4Interface(f"{self.mgmt_ips.pop(0)}/{self.mgmt_netmask}"),
                                        "gateway": str(self.mgmt_gateway)
                                    },
                                    extra_interfaces=extra_interfaces.keys(),
                                    image=str(diskimage_path),
                                    cores=machine.cores,
                                    memory=machine.memory)
                self.dismantables.insert(0, wrapper)
                wrapper.start_instance()
                extra_interfaces[f"v_{index}_m"] = "br-mgmt"
                machines[machine.name] = (wrapper, extra_interfaces, )
            except Exception as ex:
                logger.opt(exception=ex).critical(f"Unable to setup and start VM {machine.name}")
                return False

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
                    self.networks[bridge].add_device(interface)
                logger.info(f"{name} ({wrapper.ip_address}) attached to bridges: {', '.join(extra_interfaces.values())}")
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to attach VM interfaces to bridges.")
            return False

        return True
    
    def start_management_infrastructure(self, fileserver_addr: Tuple[str, int], mgmt_server_addr: Tuple[str, int]) -> bool:
        try:
            file_server = FileServer(self.base_path, fileserver_addr)
            file_server.start()
            self.dismantables.insert(0, file_server)
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to start file server")
            return False
        
        try:
            magamenet_server = ManagementServer(mgmt_server_addr, self.state_manager)
            magamenet_server.start()
            self.dismantables.insert(0, magamenet_server)
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to start managenent server")
            return False

        return True
    
    def wait_before_release(self, on_demand: bool = False):
        sleep_for = SettingsWrapper.cli_paramaters.wait

        if on_demand:
            if sleep_for != -1:
                logger.success(f"Testbed paused after stage {SettingsWrapper.cli_paramaters.pause}, CRTL+C to dismantle (Auto stop after {sleep_for}s)")
            else: 
                logger.success(f"Testbed paused after stage {SettingsWrapper.cli_paramaters.pause}, CRTL+C to dismantle (Auto stop disabled)")
        else:
            if sleep_for != -1:
                logger.success(f"Testbed is ready, CRTL+C to dismantle (Auto stop after {sleep_for}s)")
            else:
                logger.success(f"Testbed is ready, CRTL+C to dismantle (Auto stop disabled)")
        
        if sleep_for == -1:
            try: Event().wait()
            except KeyboardInterrupt:
                return

        try: time.sleep(sleep_for)
        except KeyboardInterrupt:
            return
        
    def main(self) -> bool:
        integration_start = self.integration_helper.handle_stage_start(InvokeIntegrationAfter.STARTUP)
        if integration_start == False :
            logger.critical("Critical error during integration start!")
            return False
        elif integration_start == True:
            self.dismantables.insert(0, self.integration_helper)

        if not self.setup_local_network():
            logger.critical("Critical error during local network setup!")
            return False
        
        file_server_addr = (str(self.mgmt_gateway), FILESERVER_PORT, )
        mgmt_server_addr = (str(self.mgmt_gateway), MANAGEMENT_SERVER_PORT, )
        
        try:
            influx_db = load_influxdb(str(self.mgmt_gateway), SettingsWrapper.cli_paramaters.experiment, 
                                    SettingsWrapper.cli_paramaters.dont_use_influx, SettingsWrapper.cli_paramaters.influx_path)
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to load InfluxDB data!")
            return False
        
        if influx_db.disabled:
            logger.info("InfluxDB experiment data storage is disabled!")
        else:
            logger.info(f"Experiment data will be saved to InfluxDB {influx_db.database} with tag experiment={influx_db.series_name}")

        if not load_vm_initialization(SettingsWrapper.testbed_config, self.base_path, self.state_manager, f"http://{file_server_addr[0]}:{file_server_addr[1]}"):
            logger.critical("Critical error while loading VM initialization!")
            return False

        if not self.start_management_infrastructure(file_server_addr, mgmt_server_addr):
            logger.critical("Critical error during start of management infrastructure!")
            return False

        if not self.setup_infrastructure():
            logger.critical("Critical error during setup, dismantling!")
            return False
        
        if SettingsWrapper.cli_paramaters.pause == "SETUP":
            self.wait_before_release(on_demand=True)
            return True

        logger.info("Waiting for VMs to start and initialize ...")
        if not self.state_manager.wait_for_machines_to_become_state(AgentManagementState.INITIALIZED):
            logger.critical("VMs are not ready or error during initialization!")
            return False
        logger.success("All VMs reported up & ready!")

        integration_start = self.integration_helper.handle_stage_start(InvokeIntegrationAfter.INIT)
        if integration_start == False :
            logger.critical("Critical error during integration start!")
            return False
        elif integration_start == True:
            self.dismantables.insert(0, self.integration_helper)

        if SettingsWrapper.cli_paramaters.pause == "INIT":
            self.wait_before_release(on_demand=True)
            return True
        
        logger.info("Startig experiments on VMs.")
        for machine in SettingsWrapper.testbed_config.machines:
            state = self.state_manager.get_machine(machine.name)
            message = ExperimentMessageUpstream("experiement", influx_db, machine.experiments)
            state.send_message(message.to_json().encode("utf-8"))
            state.set_state(AgentManagementState.IN_EXPERIMENT)
            
        logger.info("Waiting for VMs to finish experiments ...")
        if not self.state_manager.wait_for_machines_to_become_state(AgentManagementState.FINISHED):
            logger.critical("VMs have reported failed experiments!")
            return False
        logger.success("All VMs reported finished experiments!")
            
        if SettingsWrapper.cli_paramaters.pause == "EXPERIMENT":
            self.wait_before_release(on_demand=True)
            return True

        return True # Dismantling handeled by main
