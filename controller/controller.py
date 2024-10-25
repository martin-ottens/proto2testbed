import ipaddress
import time

from pathlib import Path
from loguru import logger
from typing import List, Tuple
from threading import Event

from helper.network_helper import NetworkBridge
from helper.instance_helper import InstanceHelper
from helper.integration_helper import IntegrationHelper
from utils.interfaces import Dismantable
from utils.config_tools import load_config, load_vm_initialization
from utils.settings import SettingsWrapper
from utils.settings import InvokeIntegrationAfter
from utils.influxdb import InfluxDBAdapter
from management_server import ManagementServer
from state_manager import MachineStateManager, AgentManagementState, WaitResult
from common.instance_manager_message import ApplicationsMessageUpstream

class Controller(Dismantable):
    def __init__(self):
        if SettingsWrapper.cli_paramaters is None:
            raise Exception("No CLIParamaters class object was set before calling the controller")

        self.networks = None
        self.dismantables: List[Dismantable] = []
        self.state_manager: MachineStateManager = MachineStateManager()
        self.has_mgmt_network = False

        self.base_path = Path(SettingsWrapper.cli_paramaters.config)
        self.config_path = self.base_path / "testbed.json"

        try:
            SettingsWrapper.testbed_config = load_config(self.config_path, 
                                                         SettingsWrapper.cli_paramaters.skip_substitution)
            self.integration_helper = IntegrationHelper(SettingsWrapper.testbed_config.integrations)
        except Exception as ex:
            logger.opt(exception=ex).critical("Internal error loading config!")
            raise Exception("Internal config loading error!")
    
    def _destory(self) -> None:
        self.setup_env = None
        self.networks = None
        self.state_manager.remove_all()

        if self.dismantables is None:
            return
        
        while len(self.dismantables) > 0:
            dismantable = self.dismantables.pop(0)
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

        self.has_mgmt_network = True
        return True

    def setup_infrastructure(self) -> bool:
        if self.networks is None:
            logger.critical("Infrastructure setup was called before local network setup!")
            return False

        for network in SettingsWrapper.testbed_config.networks:
            try:
                bridge = NetworkBridge(network.name, SettingsWrapper.cli_paramaters.clean)
                self.dismantables.insert(0, bridge)
                for pyhsical_port in network.host_ports:
                    bridge.add_device(pyhsical_port)
                bridge.start_bridge()
                self.networks[network.name] = bridge
            except Exception as ex:
                logger.opt(exception=ex).critical(f"Unable to setup additional network {network.name}")
                return False
        
        if self.integration_helper.handle_stage_start(InvokeIntegrationAfter.NETWORK) == False :
            logger.critical("Critical error during integration start!")
            return False
            
        # Setup Instances
        instances = {}
        wait_for_interfaces = []
        if self.has_mgmt_network:
            wait_for_interfaces.append("br-mgmt")

        diskimage_basepath = Path(SettingsWrapper.testbed_config.settings.diskimage_basepath)
        for index, instance in enumerate(SettingsWrapper.testbed_config.instances):
            extra_interfaces = {}

            for if_index, if_bridge in enumerate(instance.networks):
                if_int_name = f"v_{index}_{if_index}"
                extra_interfaces[if_int_name] = if_bridge
                wait_for_interfaces.append(if_int_name)

            try:
                diskimage_path = Path(instance.diskimage)

                if not diskimage_path.is_absolute():
                    diskimage_path =  diskimage_basepath / diskimage_path
                
                if not diskimage_path.exists():
                    raise Exception(f"Unable to find diskimage '{diskimage_path}'")
                
                management_settings = None
                if self.has_mgmt_network:
                    management_settings = {
                            "interface": f"v_{index}_m",
                            "ip": ipaddress.IPv4Interface(f"{self.mgmt_ips.pop(0)}/{self.mgmt_netmask}"),
                            "gateway": str(self.mgmt_gateway)
                    }

                wrapper = InstanceHelper(instance=self.state_manager.get_machine(instance.name),
                                    management=management_settings,
                                    testbed_package_path=self.base_path,
                                    extra_interfaces=extra_interfaces.keys(),
                                    image=str(diskimage_path),
                                    cores=instance.cores,
                                    memory=instance.memory,
                                    disable_kvm=SettingsWrapper.cli_paramaters.disable_kvm,
                                    netmodel=instance.netmodel)
                self.dismantables.insert(0, wrapper)
                wrapper.start_instance()

                if self.has_mgmt_network:
                    extra_interfaces[f"v_{index}_m"] = "br-mgmt"

                instances[instance.name] = (wrapper, extra_interfaces, )
            except Exception as ex:
                logger.opt(exception=ex).critical(f"Unable to setup and start instance {instance.name}")
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
            for name, instance in instances.items():
                wrapper, extra_interfaces = instance
                for interface, bridge in extra_interfaces.items():
                    self.networks[bridge].add_device(interface)
                if self.has_mgmt_network:
                    logger.info(f"{name} ({wrapper.ip_address}, {self.state_manager.get_machine(name).uuid}) attached to bridges: {', '.join(extra_interfaces.values())}")
                else:
                    logger.info(f"{name} ({self.state_manager.get_machine(name).uuid}) attached to bridges: {', '.join(extra_interfaces.values())}")
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to attach VM interfaces to bridges.")
            return False

        return True
    
    def start_management_infrastructure(self) -> bool:
        for instance in self.state_manager.get_all_machines():
            instance.prepare_interchange_dir()
        
        try:
            magamenet_server = ManagementServer(self.state_manager, SettingsWrapper.testbed_config.settings.startup_init_timeout, self.influx_db)
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
        
    def get_longest_application_duration(self) -> int:
        max_value = 0
        for instance in SettingsWrapper.testbed_config.instances:
            for application in instance.applications:
                this_value = application.delay + application.runtime
                if this_value > max_value:
                    max_value = this_value

        return max_value
        
    def main(self) -> bool:
        self.dismantables.insert(0, self.integration_helper)

        if self.integration_helper.handle_stage_start(InvokeIntegrationAfter.STARTUP) == False :
            logger.critical("Critical error during integration start!")
            return False

        if SettingsWrapper.testbed_config.settings.management_network is not None:
            if not self.setup_local_network():
                logger.critical("Critical error during local network setup!")
                return False
            else:
                logger.warning("Management Network is disabled, skipping setup.")
        
        try:
            self.influx_db = InfluxDBAdapter(SettingsWrapper.cli_paramaters.experiment, 
                                             SettingsWrapper.cli_paramaters.dont_use_influx, 
                                             SettingsWrapper.cli_paramaters.influx_path)
            self.influx_db.start()
            self.dismantables.insert(0, self.influx_db)
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to load InfluxDB data!")
            return False
        
        if self.influx_db.store_disabled:
            logger.warning("InfluxDB experiment data storage is disabled!")
        else:
            logger.success(f"Experiment data will be saved to InfluxDB {self.influx_db.database} with tag experiment={self.influx_db.series_name}")

        if not load_vm_initialization(SettingsWrapper.testbed_config, self.base_path, self.state_manager):
            logger.critical("Critical error while loading Instance initialization!")
            return False

        if not self.start_management_infrastructure():
            logger.critical("Critical error during start of management infrastructure!")
            return False

        if not self.setup_infrastructure():
            logger.critical("Critical error during instance setup")
            return False
        
        if SettingsWrapper.cli_paramaters.pause == "SETUP":
            self.wait_before_release(on_demand=True)
            return True

        logger.info("Waiting for Instances to start and initialize ...")
        
        setup_timeout = SettingsWrapper.testbed_config.settings.startup_init_timeout
        logger.debug(f"Waiting a maximum of {setup_timeout} seconds for Instances to start and initialize.")
        result: WaitResult =  self.state_manager.wait_for_machines_to_become_state(AgentManagementState.INITIALIZED, 
                                                                                   timeout=setup_timeout)
        if result == WaitResult.FAILED or result == WaitResult.TIMEOUT:
            logger.critical("Instances are not ready: Error or timeout during initialization!")
            return False
        elif result == WaitResult.INTERRUPTED:
            logger.critical("Setup was interrupted, shutting down testbed!")
            return False
        logger.success("All Instances reported up & ready!")

        if self.integration_helper.handle_stage_start(InvokeIntegrationAfter.INIT) == False :
            logger.critical("Critical error during integration start!")
            return False

        if SettingsWrapper.cli_paramaters.pause == "INIT":
            self.wait_before_release(on_demand=True)
            return True
        
        logger.info("Startig applications on Instances.")
        for machine in SettingsWrapper.testbed_config.instances:
            state = self.state_manager.get_machine(machine.name)
            message = ApplicationsMessageUpstream("experiement", machine.applications)
            state.send_message(message.to_json().encode("utf-8"))
            state.set_state(AgentManagementState.IN_EXPERIMENT)
            
        logger.info("Waiting for Instances to finish applications ...")

        experiment_timeout = SettingsWrapper.testbed_config.settings.experiment_timeout

        # Calculate by longest application
        if experiment_timeout == -1:
            experiment_timeout = self.get_longest_application_duration()
            if experiment_timeout != 0:
                experiment_timeout *= 2
    
        if experiment_timeout == 0:
            logger.error("Maximum experiment duration could not be calculated -> No applications installed!")
            if SettingsWrapper.cli_paramaters.pause == "EXPERIMENT":
                self.wait_before_release(on_demand=True)
                return True
            return False
        else:
            logger.debug(f"Waiting a maximum of {experiment_timeout} seconds for the experiment to finish.")
            result: WaitResult = self.state_manager.wait_for_machines_to_become_state(AgentManagementState.FINISHED,
                                                                                    timeout=experiment_timeout)
            if result == WaitResult.FAILED or result == WaitResult.TIMEOUT:
                logger.critical("Instances have reported failed applications or a timeout occured!")
                if SettingsWrapper.cli_paramaters.pause == "EXPERIMENT":
                    self.wait_before_release(on_demand=True)
                    return True
                return False
            elif result == WaitResult.INTERRUPTED:
                logger.critical("Waiting for applications to finish was interrupted!")
                return False
            logger.success("All Instances reported finished applications!")
            
        if SettingsWrapper.cli_paramaters.pause == "EXPERIMENT":
            self.wait_before_release(on_demand=True)
            return True

        return True # Dismantling handeled by main
