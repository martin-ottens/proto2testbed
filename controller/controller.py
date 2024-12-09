import ipaddress
import time

from pathlib import Path
from loguru import logger
from typing import List
from threading import Event, Thread

from helper.network_helper import NetworkBridge, NetworkMappingHelper
from helper.instance_helper import InstanceHelper, InstanceManagementSettings
from helper.integration_helper import IntegrationHelper
from utils.interfaces import Dismantable
from utils.config_tools import load_config, load_vm_initialization, check_preserve_dir
from utils.settings import CommonSettings, TestbedSettingsWrapper
from utils.settings import InvokeIntegrationAfter
from utils.influxdb import InfluxDBAdapter
from utils.continue_mode import *
from management_server import ManagementServer
from cli import CLI
from state_manager import MachineStateManager, AgentManagementState, WaitResult
from common.instance_manager_message import *

SUPPORTED_INSTANCE_NUMBER = 50


class Controller(Dismantable):
    def __init__(self):
        if TestbedSettingsWrapper.cli_paramaters is None:
            raise Exception("No CLIParamaters class object was set before calling the controller")

        self.dismantables: List[Dismantable] = []
        self.state_manager: MachineStateManager = MachineStateManager()
        self.dismantables.insert(0, self.state_manager)
        self.has_mgmt_network = False
        self.network_mapping: Optional[NetworkMappingHelper] = None
        self.request_restart = False

        self.base_path = Path(TestbedSettingsWrapper.cli_paramaters.config)
        self.config_path = self.base_path / "testbed.json"
        self.pause_after: PauseAfterSteps = TestbedSettingsWrapper.cli_paramaters.interact
        self.interact_finished_event: Optional[Event] = None

        self.interrupted_event = Event()
        self.interrupted_event.clear()

        try:
            self.cli = CLI(CommonSettings.log_verbose, self.state_manager)
            self.cli.start()
            self.dismantables.insert(0, self.cli)

            TestbedSettingsWrapper.testbed_config = load_config(self.config_path, 
                                                         TestbedSettingsWrapper.cli_paramaters.skip_substitution)
            self.integration_helper = IntegrationHelper(TestbedSettingsWrapper.cli_paramaters.config,
                                                        CommonSettings.app_base_path)
        except Exception as ex:
            logger.opt(exception=ex).critical("Internal error loading config!")
            raise Exception("Internal config loading error!")
    
    def _destory(self, spawn_threads: bool = True, force: bool = False) -> None:
        self.setup_env = None
        self.networks = None

        if self.dismantables is None:
            return
        
        async_dismantle = []
        while len(self.dismantables) > 0:
            dismantable = self.dismantables.pop(0)
            try:
                if not spawn_threads or not dismantable.dismantle_parallel():
                    dismantable.dismantle(force)
                else:
                    thread = Thread(target=dismantable.dismantle, daemon=True, args=(force, ))
                    thread.start()
                    async_dismantle.append(thread)
            except Exception as ex:
                logger.opt(exception=ex).error(f"Unable to dismantle {dismantable.get_name()}")

        for thread in async_dismantle:
            thread.join()

    def __del__(self):
        self._destory(spawn_threads=False, force=True)

    def dismantle(self, force: bool = False) -> None:
        self._destory(spawn_threads=(not force), force=force)
    
    def get_name(self) -> str:
        return f"Controller"
    
    def setup_local_network(self) -> bool:        
        self.network_mapping = NetworkMappingHelper()

        if TestbedSettingsWrapper.testbed_config.settings.management_network.lower() == "auto":
            self.mgmt_network = NetworkBridge.generate_auto_management_network(CommonSettings.unique_run_name)
            if self.mgmt_network is None:
                logger.critical(f"Unable to generate a management subnet for 'auto' option.")
                return False
            else:
                logger.info(f"Generated Management Network subnet '{self.mgmt_network}' for 'auto' option.")
        else:
            self.mgmt_network = ipaddress.IPv4Network(TestbedSettingsWrapper.testbed_config.settings.management_network)

            if NetworkBridge.is_network_in_use(self.mgmt_network):
                logger.critical(f"Network '{self.mgmt_network}' is already in use on this host.")
                return False

        self.mgmt_ips = list(self.mgmt_network.hosts())
        self.mgmt_netmask = ipaddress.IPv4Network(f"0.0.0.0/{self.mgmt_network.netmask}").prefixlen

        # Setup Networks
        try:
            mgmt_bridge_mapping = self.network_mapping.add_bridge_mapping("br-mgmt")
            mgmt_bridge = NetworkBridge(mgmt_bridge_mapping.dev_name, 
                                        mgmt_bridge_mapping.name)
            mgmt_bridge_mapping.bridge = mgmt_bridge
            self.dismantables.insert(0, mgmt_bridge)
            self.mgmt_gateway = self.mgmt_ips.pop(0)
            mgmt_bridge.setup_local(ip=ipaddress.IPv4Interface(f"{self.mgmt_gateway}/{self.mgmt_netmask}"), 
                                    nat=self.mgmt_network)
            mgmt_bridge.start_bridge()
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to setup management network!")
            return False

        self.has_mgmt_network = True
        return True

    def setup_infrastructure(self) -> bool:
        if self.network_mapping is None:
            logger.critical("Infrastructure setup was called before local network setup!")
            return False
        
        if len(TestbedSettingsWrapper.testbed_config.instances) > SUPPORTED_INSTANCE_NUMBER:
            logger.critical(f"{len(TestbedSettingsWrapper.testbed_config.instances)} Instances configured, a maximum of {SUPPORTED_INSTANCE_NUMBER} is supported.")
            return False

        for network in TestbedSettingsWrapper.testbed_config.networks:
            try:
                bridge_mapping = self.network_mapping.add_bridge_mapping(network.name)
                bridge = NetworkBridge(bridge_mapping.dev_name,
                                       bridge_mapping.name)
                bridge_mapping.bridge = bridge
                self.dismantables.insert(0, bridge)
                for pyhsical_port in network.host_ports:
                    bridge.add_device(pyhsical_port, is_host_port=True)
                bridge.start_bridge()
            except Exception as ex:
                logger.opt(exception=ex).critical(f"Unable to setup additional network {network.name}")
                return False
        
        if self.integration_helper.handle_stage_start(InvokeIntegrationAfter.NETWORK) == False :
            logger.critical("Critical error during integration start!")
            return False
            
        # Setup Instances
        instances = {}
        wait_for_interfaces = []
        diskimage_basepath = Path(TestbedSettingsWrapper.testbed_config.settings.diskimage_basepath)
        for instance in TestbedSettingsWrapper.testbed_config.instances:
            machine = self.state_manager.get_machine(instance.name)
            extra_interfaces = {}

            for index, if_bridge in enumerate(instance.networks):
                if_int_name = self.network_mapping.generate_tap_name()
                if_bridge_mapping = self.network_mapping.get_bridge_mapping(if_bridge)
                if if_bridge_mapping is None:
                    logger.critical(f"Unable to map network '{if_bridge}' for Instance '{instance.name}': Not mapped.")
                    return False
                extra_interfaces[if_int_name] = if_bridge_mapping
                wait_for_interfaces.append(if_int_name)
                machine.add_interface_mapping(if_bridge_mapping, 
                                              index + 1 if self.has_mgmt_network else index)

            try:
                diskimage_path = Path(instance.diskimage)

                if not diskimage_path.is_absolute():
                    diskimage_path =  diskimage_basepath / diskimage_path
                
                if not diskimage_path.exists():
                    raise Exception(f"Unable to find diskimage '{diskimage_path}'")
                
                management_settings = None
                if self.has_mgmt_network:
                    mgmt_bridge_mapping = self.network_mapping.get_bridge_mapping("br-mgmt")
                    management_settings = InstanceManagementSettings(
                        bridge_mapping=mgmt_bridge_mapping,
                        tap_dev_name=self.network_mapping.generate_tap_name(),
                        ip_interface=ipaddress.IPv4Interface(f"{self.mgmt_ips.pop(0)}/{self.mgmt_netmask}"),
                        gateway=str(self.mgmt_gateway),
                    )
                    machine.set_mgmt_ip(management_settings.ip_interface)
                    machine.add_interface_mapping(mgmt_bridge_mapping, 0)

                wrapper = InstanceHelper(instance=self.state_manager.get_machine(instance.name),
                                    management=management_settings,
                                    testbed_package_path=self.base_path,
                                    extra_interfaces=list(extra_interfaces.items()),
                                    image=str(diskimage_path),
                                    cores=instance.cores,
                                    memory=instance.memory,
                                    disable_kvm=TestbedSettingsWrapper.cli_paramaters.disable_kvm,
                                    netmodel=instance.netmodel)
                self.dismantables.insert(0, wrapper)
                wrapper.start_instance()

                if self.has_mgmt_network:
                    mgmt_if_int_name = management_settings.tap_dev_name
                    extra_interfaces[mgmt_if_int_name] = management_settings.bridge_mapping
                    wait_for_interfaces.append(mgmt_if_int_name)

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
                logger.critical("Interfaces are not ready after 20 seconds!")
                return False

            time.sleep(1)

        # Attach tap devices to bridges
        try:
            for name, instance in instances.items():
                wrapper, extra_interfaces = instance
                for interface, bridge in extra_interfaces.items():
                    bridge.bridge.add_device(interface)
                if self.has_mgmt_network:
                    logger.info(f"{name} ({wrapper.ip_address}, {self.state_manager.get_machine(name).uuid}) attached to bridges: {', '.join(list(map(lambda x: str(x), extra_interfaces.values())))}")
                else:
                    logger.info(f"{name} ({self.state_manager.get_machine(name).uuid}) attached to bridges: {', '.join(list(map(lambda x: str(x), extra_interfaces.values())))}")
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to attach Instance interfaces to bridges.")
            return False

        for instance in self.state_manager.get_all_machines():
            if not instance.update_mgmt_socket_permission():
                logger.warning(f"Unable to set socket permissions for {instance.name}")

        self.state_manager.dump_states()

        return True
    
    def start_management_infrastructure(self, init_instances_instant: bool) -> bool:
        for instance in self.state_manager.get_all_machines():
            instance.prepare_interchange_dir()
        
        try:
            magamenet_server = ManagementServer(self, self.state_manager, 
                                                TestbedSettingsWrapper.testbed_config.settings.startup_init_timeout, 
                                                self.influx_db,
                                                init_instances_instant)
            magamenet_server.start()
            self.dismantables.insert(0, magamenet_server)
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to start managenent server")
            return False

        return True
        
    def get_longest_application_duration(self) -> int:
        max_value = 0
        for instance in TestbedSettingsWrapper.testbed_config.instances:
            for application in instance.applications:
                this_value = application.delay + application.runtime
                if this_value > max_value:
                    max_value = this_value

        return max_value
    
    def send_finish_message(self):
        logger.info("Sending finish instructions to Instances")
        for machine in self.state_manager.get_all_machines():
            message = FinishInstanceMessageUpstream(machine.preserve_files, 
                                                    TestbedSettingsWrapper.cli_paramaters.preserve is not None)
            machine.send_message(message.to_json().encode("utf-8"))

        result: WaitResult = self.state_manager.wait_for_machines_to_become_state(AgentManagementState.FILES_PRESERVED,
                                                                                  timeout=30000)
        if result in [WaitResult.FAILED, WaitResult.TIMEOUT]:
            logger.critical("Instances have reported failed during file preservation or a timeout occured!")
        elif result == WaitResult.SHUTDOWN:
            logger.critical("Testbed was shut down due to an external request.")

    def stop_interaction(self, restart: bool = False):
        self.request_restart = restart
        if self.event is not None:
            self.cli.unblock_input()

    def start_interaction(self, at_step: PauseAfterSteps) -> bool:
        self.event = Event()
        contine_mode = CLIContinue(at_step)
        self.event.clear()

        if TestbedSettingsWrapper.cli_paramaters.interact is not PauseAfterSteps.DISABLE:
            self.cli.start_cli(self.event, contine_mode)
            logger.success(f"Testbed paused after stage {self.pause_after.name}, Interactive mode enabled (CRTL+C to exit).")
        else:
            logger.success(f"Testbed paused after stage {self.pause_after.name} (CRTL+C to exit).")
       
        try: 
            status = self.event.wait()
        except KeyboardInterrupt:
            self.interrupted_event.set()
            status = False

        if TestbedSettingsWrapper.cli_paramaters.interact is not PauseAfterSteps.DISABLE:
            self.cli.stop_cli()
        
        if not status:
            return False
        else:
            if contine_mode.mode == ContinueMode.EXIT:
                return False
            if contine_mode.mode == ContinueMode.RESTART:
                self.request_restart = True
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
            self.interrupted_event.set()
            logger.critical(f"Action '{stage}' was interrupted!")
            return False
        elif result == WaitResult.SHUTDOWN:
            if self.interact_finished_event is not None:
                self.interact_finished_event.set()
                self.cli.stop_cli()
            logger.warning("Shutting down testbed due to command from Instance!")
            self.send_finish_message()
            return False
        else:
            return True
        
    def main(self) -> bool:
        self.integration_helper.apply_configured_integrations(TestbedSettingsWrapper.testbed_config.integrations)
        self.dismantables.insert(0, self.integration_helper)

        try:
            self.influx_db = InfluxDBAdapter(CommonSettings.experiment, 
                                             TestbedSettingsWrapper.cli_paramaters.dont_use_influx, 
                                             CommonSettings.influx_path)
            self.influx_db.start()
            self.dismantables.insert(0, self.influx_db)
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to load InfluxDB data!")
            return False
        
        if not check_preserve_dir(TestbedSettingsWrapper.cli_paramaters.preserve):
            logger.critical("Unable to set up File Preservation")
            return False
        self.state_manager.enable_file_preservation(TestbedSettingsWrapper.cli_paramaters.preserve)

        if self.integration_helper.handle_stage_start(InvokeIntegrationAfter.STARTUP) == False :
            logger.critical("Critical error during integration start!")
            return False

        if TestbedSettingsWrapper.testbed_config.settings.management_network is not None:
            if not self.setup_local_network():
                logger.critical("Critical error during local network setup!")
                return False
        else:
            logger.warning("Management Network is disabled, skipping setup.")
        
        if self.influx_db.store_disabled:
            logger.warning("InfluxDB experiment data storage is disabled!")
        else:
            logger.success(f"Experiment data will be saved to InfluxDB {self.influx_db.database} with tag experiment={self.influx_db.series_name}")

        if not load_vm_initialization(TestbedSettingsWrapper.testbed_config, self.base_path, self.state_manager):
            logger.critical("Critical error while loading Instance initialization!")
            return False

        if not self.start_management_infrastructure(self.pause_after != PauseAfterSteps.SETUP):
            logger.critical("Critical error during start of management infrastructure!")
            return False

        if not self.setup_infrastructure():
            logger.critical("Critical error during instance setup")
            return False

        setup_timeout = TestbedSettingsWrapper.testbed_config.settings.startup_init_timeout
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

        if not self.wait_for_to_become(setup_timeout, "Instance Initialization", 
                                       AgentManagementState.INITIALIZED, 
                                       self.pause_after == PauseAfterSteps.INIT):
            return False

        logger.info("Instances are initialized, invoking installtion of apps ...")
        for config_machine in TestbedSettingsWrapper.testbed_config.instances:
            machine = self.state_manager.get_machine(config_machine.name)
            apps = config_machine.applications
            machine.add_apps(apps)
            machine.set_state(AgentManagementState.APPS_SENDED)
            machine.send_message(InstallApplicationsMessageUpstream(apps).to_json().encode("utf-8"))
        
        if not self.wait_for_to_become(setup_timeout, 'App Installation', 
                                AgentManagementState.APPS_READY, 
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
        message = RunApplicationsMessageUpstream().to_json().encode("utf-8")
        for machine in self.state_manager.get_all_machines():
            machine.send_message(message)
            machine.set_state(AgentManagementState.IN_EXPERIMENT)
            
        logger.info("Waiting for Instances to finish applications ...")

        experiment_timeout = TestbedSettingsWrapper.testbed_config.settings.experiment_timeout

        # Calculate by longest application
        if experiment_timeout == -1:
            experiment_timeout = self.get_longest_application_duration() + 10
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
