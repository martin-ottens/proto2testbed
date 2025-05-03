#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2024-2025 Martin Ottens
# 
# This program is free software: you can redistribute it and/or modify 
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful, 
# but WITHOUT ANY WARRANTY; without even the implied warranty of 
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the 
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License 
# along with this program. If not, see https://www.gnu.org/licenses/.
#

import ipaddress
import time

from pathlib import Path
from loguru import logger
from typing import List, Dict
from threading import Event, Thread

from helper.network_helper import *
from helper.instance_helper import InstanceHelper, InstanceManagementSettings
from helper.integration_helper import IntegrationHelper
from utils.interfaces import Dismantable
from utils.config_tools import load_config, load_vm_initialization, check_preserve_dir
from utils.settings import CommonSettings, TestbedSettingsWrapper
from utils.settings import InvokeIntegrationAfter
from utils.influxdb import InfluxDBAdapter
from utils.networking import *
from utils.continue_mode import *
from management_server import ManagementServer
from cli import CLI
from state_manager import InstanceStateManager, AgentManagementState, WaitResult, InstanceState
from common.instance_manager_message import *
from constants import SUPPORTED_INSTANCE_NUMBER


class Controller(Dismantable):
    def __init__(self):
        if TestbedSettingsWrapper.cli_paramaters is None:
            raise Exception("No CLIParamaters class object was set before calling the controller")

        self.dismantables: List[Dismantable] = []
        self.state_manager: InstanceStateManager = InstanceStateManager()
        self.dismantables.insert(0, self.state_manager)
        self.mgmt_bridge: Optional[ManagementNetworkBridge] = None
        self.mgmt_bridge_mapping: Optional[BridgeMapping] = None
        self.network_mapping = NetworkMappingHelper()
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
        if TestbedSettingsWrapper.testbed_config.settings.management_network.lower() == "auto":
            mgmt_network = NetworkBridge.generate_auto_management_network(CommonSettings.unique_run_name)
            if mgmt_network is None:
                logger.critical(f"Unable to generate a management subnet for 'auto' option.")
                return False
            else:
                logger.info(f"Generated Management Network subnet '{mgmt_network}' for 'auto' option.")
        else:
            mgmt_network = ipaddress.IPv4Network(TestbedSettingsWrapper.testbed_config.settings.management_network)

            if NetworkBridge.is_network_in_use(mgmt_network):
                logger.critical(f"Network '{mgmt_network}' is already in use on this host.")
                return False

        # Setup management network bridge
        try:
            self.mgmt_bridge_mapping = self.network_mapping.add_bridge_mapping("br-mgmt")
            self.mgmt_bridge = ManagementNetworkBridge(self.mgmt_bridge_mapping.dev_name, 
                                                       self.mgmt_bridge_mapping.name,
                                                       mgmt_network)
            self.mgmt_bridge_mapping.bridge = self.mgmt_bridge
            self.dismantables.insert(0, self.mgmt_bridge)
            self.mgmt_bridge.setup_local()
            self.mgmt_bridge.start_bridge()
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to setup management network!")
            return False

        return True

    def setup_infrastructure(self) -> bool:
        if self.network_mapping is None:
            logger.critical("Infrastructure setup was called before local network setup!")
            return False
        
        if len(TestbedSettingsWrapper.testbed_config.instances) > SUPPORTED_INSTANCE_NUMBER:
            logger.critical(f"{len(TestbedSettingsWrapper.testbed_config.instances)} Instances configured, a maximum of {SUPPORTED_INSTANCE_NUMBER} is supported.")
            return False

        # Create bridges for experiment networks
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
        wait_for_interfaces: List[str] = []
        diskimage_basepath = Path(TestbedSettingsWrapper.testbed_config.settings.diskimage_basepath)
        for instance_config in TestbedSettingsWrapper.testbed_config.instances:
            instance = self.state_manager.get_instance(instance_config.name)

            for index, attached_network in enumerate(instance_config.networks):
                tap_name = self.network_mapping.generate_tap_name()
                bridge_mapping = self.network_mapping.get_bridge_mapping(attached_network.name)
                if bridge_mapping is None:
                    logger.critical(f"Unable to map network '{attached_network.name}' for Instance '{instance_config.name}': Not mapped.")
                    return False

                wait_for_interfaces.append(tap_name)
                instance_interface = InstanceInterface(
                    tap_index=(index + 1 if self.mgmt_bridge is not None else index),
                    tap_dev=tap_name,
                    tap_mac=attached_network.mac,
                    netmodel=attached_network.netmodel,
                    bridge=bridge_mapping,
                    instance=instance
                )
                instance.add_interface_mapping(instance_interface)

            try:
                diskimage_path = Path(instance_config.diskimage)

                if not diskimage_path.is_absolute():
                    diskimage_path =  diskimage_basepath / diskimage_path
                
                if not diskimage_path.exists():
                    raise Exception(f"Unable to find diskimage '{diskimage_path}'")
                
                management_settings = None
                if self.mgmt_bridge is not None:
                    intstance_mgmt_ip = self.mgmt_bridge.get_next_mgmt_ip()
                    tap_name = self.network_mapping.generate_tap_name()
                    instance.set_mgmt_ip(intstance_mgmt_ip)

                    wait_for_interfaces.append(tap_name)
                    instance_interface = InstanceInterface(
                        tap_index=0,
                        tap_dev=tap_name,
                        bridge=self.mgmt_bridge_mapping,
                        is_management_interface=True,
                        instance=instance_config
                    )
                    instance.add_interface_mapping(instance_interface)

                    management_settings = InstanceManagementSettings(
                        interface=instance_interface,
                        ip_interface=intstance_mgmt_ip,
                        gateway=self.mgmt_bridge.mgmt_gateway,
                    )


                helper = InstanceHelper(instance=instance,
                                    management=management_settings,
                                    testbed_package_path=self.base_path,
                                    image=str(diskimage_path),
                                    cores=instance_config.cores,
                                    memory=instance_config.memory,
                                    disable_kvm=TestbedSettingsWrapper.cli_paramaters.disable_kvm)
                self.dismantables.insert(0, helper)
                helper.start_instance()
            except Exception as ex:
                logger.opt(exception=ex).critical(f"Unable to setup and start instance {instance_config.name}")
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
            for instance_config in self.state_manager.get_all_instances():
                interface: InstanceInterface
                bridge_list: List[str] = []
                for interface in instance_config.interfaces:
                    interface.bridge.bridge.add_device(interface.tap_dev)
                    interface.bridge_attached = True
                    bridge_list.append(interface.bridge_name)
                
                if self.mgmt_bridge is not None:
                    logger.info(f"{instance_config.name} ({instance_config.mgmt_ip_addr}, {instance_config.uuid}) attached to bridges: {', '.join(bridge_list)}")
                else:
                    logger.info(f"{instance_config.name} ({instance_config.uuid}) attached to bridges: {', '.join(bridge_list)}")
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to attach Instance interfaces to bridges.")
            return False

        for instance_config in self.state_manager.get_all_instances():
            if not instance_config.update_mgmt_socket_permission():
                logger.warning(f"Unable to set socket permissions for {instance_config.name}")

        self.state_manager.dump_states()

        return True
    
    def start_management_infrastructure(self, init_instances_instant: bool) -> bool:
        for instance in self.state_manager.get_all_instances():
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
        for instance in self.state_manager.get_all_instances():
            if not instance.is_connected():
                continue

            message = FinishInstanceMessageUpstream(instance.preserve_files, 
                                                    TestbedSettingsWrapper.cli_paramaters.preserve is not None)
            instance.send_message(message.to_json().encode("utf-8"))

        result: WaitResult = self.state_manager.wait_for_instances_to_become_state([AgentManagementState.FILES_PRESERVED, 
                                                                                   AgentManagementState.DISCONNECTED],
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

    def wait_for_to_become(self, timeout: int, stage: str, 
                           waitstate: AgentManagementState, 
                           interact_on_failure: bool = True,
                           request_file_preservation: bool = True) -> bool:
        logger.debug(f"Waiting a maximum of {timeout} seconds for action '{stage}' to finish.")
        result: WaitResult = self.state_manager.wait_for_instances_to_become_state([waitstate], timeout)
        if result == WaitResult.FAILED or result == WaitResult.TIMEOUT:
            logger.critical(f"Instances have reported failure during action '{stage}' or a timeout occured!")
            if interact_on_failure:
                self.start_interaction(PauseAfterSteps.DISABLE)
            if request_file_preservation:
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
                                             TestbedSettingsWrapper.cli_paramaters.dont_use_influx)
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
                                           AgentManagementState.STARTED, False, False):
                return False

            if not self.start_interaction(PauseAfterSteps.SETUP):
                self.send_finish_message()
                return True
            
            for instance in self.state_manager.get_all_instances():
                instance.send_message(InitializeMessageUpstream(
                            instance.get_setup_env()[0], 
                            instance.get_setup_env()[1]).to_json().encode("utf-8"))
        else:
            logger.info("Waiting for Instances to start and initialize ...")

        if not self.wait_for_to_become(setup_timeout, "Instance Initialization", 
                                       AgentManagementState.INITIALIZED, 
                                       self.pause_after == PauseAfterSteps.INIT, True):
            return False

        logger.info("Instances are initialized, invoking installtion of apps ...")
        for config_instance in TestbedSettingsWrapper.testbed_config.instances:
            instance = self.state_manager.get_instance(config_instance.name)
            apps = config_instance.applications
            instance.add_apps(apps)
            instance.set_state(AgentManagementState.APPS_SENDED)
            instance.send_message(InstallApplicationsMessageUpstream(apps).to_json().encode("utf-8"))
        
        if not self.wait_for_to_become(setup_timeout, 'App Installation', 
                                AgentManagementState.APPS_READY, 
                                self.pause_after == PauseAfterSteps.INIT, True):
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
        for instance in self.state_manager.get_all_instances():
            instance.send_message(message)
            instance.set_state(AgentManagementState.IN_EXPERIMENT)
            
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
                                    self.pause_after == PauseAfterSteps.EXPERIMENT, True)
            logger.success("All Instances reported finished applications!")
            
        if self.pause_after == PauseAfterSteps.EXPERIMENT:
            self.start_interaction(PauseAfterSteps.EXPERIMENT)
        
        self.send_finish_message()

        return True # Dismantling handeled by main
