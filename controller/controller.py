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
from utils.config_tools import load_config, load_vm_initialization, check_preserve_dir
from utils.settings import SettingsWrapper
from utils.settings import InvokeIntegrationAfter
from utils.influxdb import InfluxDBAdapter
from utils.continue_mode import *
from management_server import ManagementServer
from cli import CLI
from state_manager import MachineStateManager, AgentManagementState, WaitResult
from common.instance_manager_message import InitializeMessageUpstream, ApplicationsMessageUpstream, FinishInstanceMessageUpstream

class Controller(Dismantable):
    def __init__(self):
        if SettingsWrapper.cli_paramaters is None:
            raise Exception("No CLIParamaters class object was set before calling the controller")

        self.networks = {}
        self.dismantables: List[Dismantable] = []
        self.state_manager: MachineStateManager = MachineStateManager()
        self.has_mgmt_network = False

        self.base_path = Path(SettingsWrapper.cli_paramaters.config)
        self.config_path = self.base_path / "testbed.json"
        self.pause_after: PauseAfterSteps = SettingsWrapper.cli_paramaters.pause

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
        try:
            mgmt_bridge = NetworkBridge("br-mgmt", SettingsWrapper.cli_paramaters.clean)
            self.dismantables.insert(0, mgmt_bridge)
            self.mgmt_gateway = self.mgmt_ips.pop(0)
            mgmt_bridge.setup_local(ip=ipaddress.IPv4Interface(f"{self.mgmt_gateway}/{self.mgmt_netmask}"), 
                                    nat=self.mgmt_network)
            mgmt_bridge.start_bridge()
            self.networks["br-mgmt"] = mgmt_bridge
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to setup management network!")
            return False

        self.has_mgmt_network = True
        return True

    def setup_infrastructure(self) -> bool:
        if self.has_mgmt_network and len(self.networks) == 0:
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
                    wait_for_interfaces.append(f"v_{index}_m")

                instances[instance.name] = (wrapper, extra_interfaces, )
            except Exception as ex:
                logger.opt(exception=ex).critical(f"Unable to setup and start instance {instance.name}")
                return False

        # Wait for tap devices to become ready
        wait_until = time.time() + 60
        while True:
            if NetworkBridge.check_interfaces_available(wait_for_interfaces):
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

        for instance in self.state_manager.get_all_machines():
            if not instance.update_mgmt_socket_permission():
                logger.warning(f"Unable to set socket permissions for {instance.name}")

        return True
    
    def start_management_infrastructure(self, init_instances_instant: bool) -> bool:
        for instance in self.state_manager.get_all_machines():
            instance.prepare_interchange_dir()
        
        try:
            magamenet_server = ManagementServer(self.state_manager, 
                                                SettingsWrapper.testbed_config.settings.startup_init_timeout, 
                                                self.influx_db,
                                                init_instances_instant)
            magamenet_server.start()
            self.dismantables.insert(0, magamenet_server)
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to start managenent server")
            return False

        return True
    
    def wait_before_release(self, event: Event, on_demand: bool = False) -> bool:
        if on_demand:
            logger.success(f"Testbed paused after stage {self.pause_after.name}, Interactive mode enabled (CRTL+C to exit).")
        else:
            logger.success(f"Testbed is ready, Interactive mode enabled (CRTL+C to exit).")
       
        try: 
            return event.wait()
        except KeyboardInterrupt:
            return False
        
    def get_longest_application_duration(self) -> int:
        max_value = 0
        for instance in SettingsWrapper.testbed_config.instances:
            for application in instance.applications:
                this_value = application.delay + application.runtime
                if this_value > max_value:
                    max_value = this_value

        return max_value
    
    def send_finish_message(self):
        logger.info("Sending finish instructions to Instances")
        for machine in SettingsWrapper.testbed_config.instances:
            state = self.state_manager.get_machine(machine.name)
            message = FinishInstanceMessageUpstream(machine.preserve_files)
            state.send_message(message.to_json().encode("utf-8"))

        result: WaitResult = self.state_manager.wait_for_machines_to_become_state(AgentManagementState.FILES_PRESERVED,
                                                                                  timeout=30)
        if result == WaitResult.FAILED or result == WaitResult.TIMEOUT:
            logger.critical("Instances have reported failed during file preservation or a timeout occured!")

    def start_interaction(self, at_step: PauseAfterSteps) -> bool:
        event = Event()
        contine_mode = CLIContinue(at_step)
        event.clear()
        self.cli.start_cli(event, contine_mode)
        status = self.wait_before_release(event, on_demand=True)
        self.cli.stop_cli()
        
        if not status:
            return False
        else:
            if contine_mode.mode == ContinueMode.EXIT:
                return False
            else: # ContinueMode.CONTINUE_TO
                self.pause_after = contine_mode.pause
                return True

    def wait_for_to_become(self, timeout: int, stage: str, waitstate: AgentManagementState, interact_on_failure: bool = True):
        logger.debug(f"Waiting a maximum of {timeout} seconds for action '{stage}' to finish.")
        result: WaitResult = self.state_manager.wait_for_machines_to_become_state(waitstate, timeout)
        if result == WaitResult.FAILED or result == WaitResult.TIMEOUT:
            logger.critical(f"Instances have reported failure during action '{stage}' or a timeout occured!")
            if interact_on_failure:
                self.start_interaction(PauseAfterSteps.DISABLE)
                self.send_finish_message()
            return False
        elif result == WaitResult.INTERRUPTED:
            logger.critical(f"Action '{stage}' was interrupted!")
            return False
        else:
            return True
        
    def main(self) -> bool:
        self.cli = CLI(SettingsWrapper.cli_paramaters.log_quiet, 
                       SettingsWrapper.cli_paramaters.log_verbose, 
                       self.state_manager)
        self.cli.start()
        self.dismantables.insert(0, self.cli)

        self.dismantables.insert(0, self.integration_helper)

        try:
            self.influx_db = InfluxDBAdapter(SettingsWrapper.cli_paramaters.experiment, 
                                             SettingsWrapper.cli_paramaters.dont_use_influx, 
                                             SettingsWrapper.cli_paramaters.influx_path)
            self.influx_db.start()
            self.dismantables.insert(0, self.influx_db)
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to load InfluxDB data!")
            return False
        
        if not check_preserve_dir(SettingsWrapper.cli_paramaters.preserve):
            logger.critical("Unable to set up File Preservation")
            return False
        self.state_manager.enable_file_preservation(SettingsWrapper.cli_paramaters.preserve)

        if self.integration_helper.handle_stage_start(InvokeIntegrationAfter.STARTUP) == False :
            logger.critical("Critical error during integration start!")
            return False

        if SettingsWrapper.testbed_config.settings.management_network is not None:
            if not self.setup_local_network():
                logger.critical("Critical error during local network setup!")
                return False
        else:
            logger.warning("Management Network is disabled, skipping setup.")
        
        if self.influx_db.store_disabled:
            logger.warning("InfluxDB experiment data storage is disabled!")
        else:
            logger.success(f"Experiment data will be saved to InfluxDB {self.influx_db.database} with tag experiment={self.influx_db.series_name}")

        if not load_vm_initialization(SettingsWrapper.testbed_config, self.base_path, self.state_manager):
            logger.critical("Critical error while loading Instance initialization!")
            return False

        if not self.start_management_infrastructure(self.pause_after != PauseAfterSteps.SETUP):
            logger.critical("Critical error during start of management infrastructure!")
            return False

        if not self.setup_infrastructure():
            logger.critical("Critical error during instance setup")
            return False

        setup_timeout = SettingsWrapper.testbed_config.settings.startup_init_timeout        
        if self.pause_after == PauseAfterSteps.SETUP:
            logger.info("Waiting for Instances to start ...")

            if not self.wait_for_to_become(setup_timeout, "Infrastructure Setup", 
                                           AgentManagementState.STARTED, False):
                return False

            if not self.start_interaction(PauseAfterSteps.SETUP):
                self.send_finish_message()
                return True
            
            for machine in self.state_manager.get_all_machines():
                machine.send_message(InitializeMessageUpstream(
                            machine.get_setup_env()[0], 
                            machine.get_setup_env()[1]).to_json().encode("utf-8"))
        else:
            logger.info("Waiting for Instances to start and initialize ...")
        
        if not self.wait_for_to_become(setup_timeout, 'Instance Initialization', 
                                AgentManagementState.INITIALIZED, 
                                self.pause_after == PauseAfterSteps.INIT):
            return False
        
        logger.success("All Instances reported up & ready!")

        if self.integration_helper.handle_stage_start(InvokeIntegrationAfter.INIT) == False :
            logger.critical("Critical error during integration start!")
            return False

        if self.pause_after == PauseAfterSteps.INIT:
            if not self.start_interaction(PauseAfterSteps.INIT):
                self.send_finish_message()
                return True
        
        logger.info("Startig applications on Instances.")
        for machine in SettingsWrapper.testbed_config.instances:
            state = self.state_manager.get_machine(machine.name)
            message = ApplicationsMessageUpstream(machine.applications)
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
            if self.pause_after == PauseAfterSteps.EXPERIMENT:
                self.start_interaction(PauseAfterSteps.EXPERIMENT)
                self.send_finish_message()
            return False
        else:
            self.wait_for_to_become(experiment_timeout, 'Experiment', 
                                    AgentManagementState.FINISHED, 
                                    self.pause_after == PauseAfterSteps.EXPERIMENT)
            logger.success("All Instances reported finished applications!")
            
        if self.pause_after == PauseAfterSteps.EXPERIMENT:
            self.start_interaction(PauseAfterSteps.EXPERIMENT)
        
        self.send_finish_message()

        return True # Dismantling handeled by main
