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
from typing import List
from threading import Event, Thread

from helper.network_helper import *
from helper.instance_helper import InstanceHelper, InstanceManagementSettings
from helper.integration_helper import IntegrationHelper
from helper.app_dependency_helper import AppDependencyHelper
from helper.state_file_helper import StateFileReader
from utils.interfaces import Dismantable
from utils.config_tools import load_vm_initialization, check_preserve_dir
from utils.state_provider import TestbedStateProvider
from utils.settings import InvokeIntegrationAfter, RunParameters
from utils.influxdb import InfluxDBAdapter
from utils.networking import *
from utils.continue_mode import *
from management_server import ManagementServer
from cli import CLI
from state_manager import InstanceStateManager, AgentManagementState, WaitResult
from common.instance_manager_message import *
from full_result_wrapper import FullResultWrapper
from constants import SUPPORTED_INSTANCE_NUMBER


class Controller(Dismantable):
    def __init__(self, provider: TestbedStateProvider) -> None:
        self.provider = provider
        self.cli = CLI(self.provider)

    def init_config(self, run_parameters: RunParameters, testbed_basepath: str) -> None:
        if self.provider.testbed_config is None:
            raise Exception("Cannot start controller without testbed config!")

        self.run_parameters = run_parameters
        self.testbed_basepath = testbed_basepath
        self.dismantables: List[Dismantable] = []
        self.state_manager: InstanceStateManager = InstanceStateManager(self.provider)
        self.dismantables.insert(0, self.state_manager)
        self.mgmt_bridge: Optional[ManagementNetworkBridge] = None
        self.mgmt_bridge_mapping: Optional[BridgeMapping] = None
        self.network_mapping = NetworkMappingHelper()
        self.request_restart = False
        self.influx_db = None

        self.base_path = Path(testbed_basepath)
        self.pause_after: PauseAfterSteps = self.run_parameters.interact
        self.interact_finished_event: Optional[Event] = None

        self.interrupted_event = Event()
        self.interaction_event = None
        self.interrupted_event.clear()
        self.app_dependencies: Optional[AppDependencyHelper] = None

        reader = StateFileReader(self.provider)
        all_experiments = reader.get_other_experiments(self.provider.experiment)

        if len(all_experiments) != 0:
            err = f"Other testbeds with same experiment tag are running: "
            err += ', '.join([f"User:{user}/PID:{pid}" for user, pid in all_experiments.items()])
            raise Exception(err)
        
        if self.run_parameters.preserve is not None:
            try:
                if not bool(self.run_parameters.preserve.anchor or self.run_parameters.preserve.name):
                    raise Exception("Invalid preserve path")
            except Exception as ex:
                raise Exception("Unable to start: Preserve Path is not valid!") from ex

        try:
            self.cli.start()
            self.dismantables.insert(0, self.cli)
            self.app_dependencies = AppDependencyHelper(self.provider.testbed_config)
            self.app_dependencies.compile_dependency_list()
            self.state_manager.set_app_dependecy_helper(self.app_dependencies)
            self.integration_helper = IntegrationHelper(testbed_basepath,
                                                        str(self.provider.app_base_path),
                                                        self.provider.default_configs.get_defaults("disable_integrations", False))
            full_result_wrapper = FullResultWrapper(self.provider.testbed_config)
            self.provider.set_full_result_wrapper(full_result_wrapper)
            self.cli.set_full_result_wrapper(full_result_wrapper)

        except Exception as ex:
            raise Exception("Error during config validation error!") from ex
        
        self.integration_helper.apply_configured_integrations(self.provider.testbed_config.integrations)
        self.dismantables.insert(0, self.integration_helper)

        try:
            self.influx_db = InfluxDBAdapter(self.provider, self.run_parameters.dont_use_influx,
                                             full_result_wrapper=self.provider.result_wrapper if self.provider.cache_datapoints else None)
            self.influx_db.start()
            self.dismantables.insert(0, self.influx_db)
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to load InfluxDB data!")
            return False
    
    def _destroy(self, spawn_threads: bool = True, force: bool = False) -> None:
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
        self._destroy(spawn_threads=False, force=True)

    def dismantle(self, force: bool = False) -> None:
        self._destroy(spawn_threads=(not force), force=force)
    
    def get_name(self) -> str:
        return f"Controller"
    
    def setup_local_network(self) -> bool:
        autogenerated = False
        if self.provider.testbed_config.settings.management_network.lower() == "auto":
            mgmt_network = NetworkBridge.generate_auto_management_network(
                                self.provider.unique_run_name, 
                                self.provider.default_configs.get_defaults("management_network"))

            if mgmt_network is None:
                logger.critical(f"Unable to generate a management subnet for 'auto' option.")
                return False
            else:
                logger.info(f"Generated Management Network subnet '{mgmt_network}' for 'auto' option.")
                autogenerated = True
        else:
            mgmt_network = ipaddress.IPv4Network(self.provider.testbed_config.settings.management_network)

            if NetworkBridge.is_network_in_use(mgmt_network):
                logger.critical(f"Network '{mgmt_network}' is already in use on this host.")
                return False

        # Setup management network bridge
        try:
            bridge_name = self.provider.concurrency_reservation.generate_new_bridge_names()[0]
            self.mgmt_bridge_mapping = self.network_mapping.add_bridge_mapping("br-mgmt", bridge_name)
            self.mgmt_bridge = ManagementNetworkBridge(self.mgmt_bridge_mapping.dev_name, 
                                                       self.mgmt_bridge_mapping.name,
                                                       mgmt_network, autogenerated)
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
        
        if len(self.provider.testbed_config.instances) > SUPPORTED_INSTANCE_NUMBER:
            logger.critical(f"{len(self.provider.testbed_config.instances)} Instances configured, a maximum of {SUPPORTED_INSTANCE_NUMBER} is supported.")
            return False

        # Create bridges for experiment networks
        bridge_names = self.provider.concurrency_reservation.generate_new_bridge_names(len(self.provider.testbed_config.networks))
        for index, network in enumerate(self.provider.testbed_config.networks):
            try:
                bridge_mapping = self.network_mapping.add_bridge_mapping(network.name, bridge_names[index])
                bridge = NetworkBridge(bridge_mapping.dev_name,
                                       bridge_mapping.name)
                bridge_mapping.bridge = bridge
                self.dismantables.insert(0, bridge)
                for physical_port in network.host_ports:
                    bridge.add_device(physical_port, is_host_port=True)
                bridge.start_bridge()
            except Exception as ex:
                logger.opt(exception=ex).critical(f"Unable to setup additional network {network.name}")
                return False
        
        start_status = self.integration_helper.handle_stage_start(InvokeIntegrationAfter.NETWORK)
        if start_status is None:
            logger.debug(f"No integration scheduled for start at stage {InvokeIntegrationAfter.NETWORK}")
        elif start_status is False:
            logger.critical("Critical error during integration start!")
            return False

        # Setup Instances
        wait_for_interfaces: List[str] = []
        diskimage_basepath = Path(self.provider.testbed_config.settings.diskimage_basepath)
        for instance_config in self.provider.testbed_config.instances:
            instance = self.state_manager.get_instance(instance_config.name)
            
            tap_names = self.provider.concurrency_reservation.generate_new_tap_names(len(instance_config.networks))
            
            for index, attached_network in enumerate(instance_config.networks):
                tap_name = tap_names[index]
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
                    vhost_enabled=attached_network.vhost,
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

                    if instance_config.management_address is not None:
                        instance_mgmt_ip = self.mgmt_bridge.check_address_available_and_reserve(
                                                instance_config.management_address)
                        if not instance_mgmt_ip:
                            raise Exception("Unable to assign requested management IP address")
                        else:
                            logger.trace(f"Using fixed management address '{instance_mgmt_ip}' for Instance {instance_config.name}.")
                    else:
                        instance_mgmt_ip = self.mgmt_bridge.get_next_mgmt_ip()
                        logger.trace(f"Using generated management address '{instance_mgmt_ip}' for Instance {instance_config.name}.")

                    tap_name = self.provider.concurrency_reservation.generate_new_tap_names()[0]
                    instance.set_mgmt_ip(str(instance_mgmt_ip))

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
                        ip_interface=instance_mgmt_ip,
                        gateway=self.mgmt_bridge.mgmt_gateway,
                    )
                elif instance_config.management_address is not None:
                    raise Exception("Management address is configured, but management network not enabled.")


                helper = InstanceHelper(instance=instance,
                                        management=management_settings,
                                        testbed_package_path=str(self.base_path),
                                        image=str(diskimage_path),
                                        cores=instance_config.cores,
                                        memory=instance_config.memory,
                                        allow_gso_gro=self.provider.testbed_config.settings.allow_gso_gro,
                                        disable_kvm=self.run_parameters.disable_kvm)
                self.dismantables.insert(0, helper)
                helper.start_instance()
            except Exception as ex:
                logger.opt(exception=ex).critical(f"Unable to setup and start instance {instance_config.name}")
                return False

        # Wait for tap devices to become ready
        wait_until = time.time() + self.provider.testbed_config.settings.startup_init_timeout
        while True:
            if NetworkBridge.check_interfaces_available(wait_for_interfaces):
                break

            if time.time() > wait_until:
                logger.critical(f"Interfaces are not ready after {self.provider.testbed_config.settings.startup_init_timeout} seconds!")
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
            management_server = ManagementServer(self, self.state_manager,
                                                self.provider.testbed_config.settings.startup_init_timeout, 
                                                self.influx_db,
                                                init_instances_instant)
            management_server.start()
            self.dismantables.insert(0, management_server)
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to start management server")
            return False

        return True
    
    def send_finish_message(self):
        logger.info("Sending finish instructions to Instances")
        for instance in self.state_manager.get_all_instances():
            if not instance.is_connected():
                continue

            message = FinishInstanceMessageUpstream(instance.preserve_files,
                                                    self.run_parameters.preserve is not None)
            instance.send_message(message)

        result: WaitResult = self.state_manager.wait_for_instances_to_become_state([AgentManagementState.STARTED,
                                                                                    AgentManagementState.APPS_SENDED,
                                                                                    AgentManagementState.FILES_PRESERVED, 
                                                                                    AgentManagementState.DISCONNECTED,
                                                                                    AgentManagementState.UNKNOWN],
                                                                                   timeout=self.provider.testbed_config.settings.file_preservation_timeout)
        if result in [WaitResult.FAILED, WaitResult.TIMEOUT]:
            logger.critical("Instances have reported failed during file preservation or a timeout occurred!")
        elif result == WaitResult.SHUTDOWN:
            logger.critical("Testbed was shut down due to an external request.")

    def stop_interaction(self, restart: bool = False):
        self.request_restart = restart
        if self.interaction_event is not None:
            self.cli.unblock_input()

    def start_interaction(self, at_step: PauseAfterSteps) -> bool:
        self.interaction_event = Event()
        continue_mode = CLIContinue(at_step)
        self.interaction_event.clear()

        if self.run_parameters.interact is not PauseAfterSteps.DISABLE:
            self.cli.start_cli(self.interaction_event, continue_mode)
            logger.success(f"Testbed paused after stage {self.pause_after.name}, Interactive mode enabled (CRTL+C to exit).")
        else:
            logger.success(f"Testbed paused after stage {self.pause_after.name} (CRTL+C to exit).")
       
        try: 
            status = self.interaction_event.wait()
        except KeyboardInterrupt:
            self.interrupted_event.set()
            status = False

        if self.run_parameters.interact is not PauseAfterSteps.DISABLE:
            self.cli.stop_cli()
        
        if not status:
            return False
        else:
            if continue_mode.mode == ContinueMode.EXIT:
                return False
            if continue_mode.mode == ContinueMode.RESTART:
                self.request_restart = True
                return False
            else: # ContinueMode.CONTINUE_TO
                self.pause_after = continue_mode.pause
                return True

    def wait_for_to_become(self, timeout: int, stage: str, 
                           waitstate: AgentManagementState, 
                           interact_on_failure: bool = True,
                           request_file_preservation: bool = True) -> bool:
        logger.debug(f"Waiting a maximum of {timeout} seconds for action '{stage}' to finish.")
        result: WaitResult = self.state_manager.wait_for_instances_to_become_state([waitstate], timeout)
        if result == WaitResult.FAILED or result == WaitResult.TIMEOUT:
            logger.critical(f"Instances have reported failure during action '{stage}' or a timeout occurred!")
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
        if not check_preserve_dir(self.run_parameters.preserve, self.provider.executor):
            logger.critical("Unable to set up File Preservation")
            return False
        self.state_manager.enable_file_preservation(self.run_parameters.preserve)

        start_status = self.integration_helper.handle_stage_start(InvokeIntegrationAfter.STARTUP)
        if start_status is None:
            logger.debug(f"No integration scheduled for start at stage {InvokeIntegrationAfter.STARTUP}")
        elif start_status is False:
            logger.critical("Critical error during integration start!")
            return False

        if self.provider.testbed_config.settings.management_network is not None:
            if not self.setup_local_network():
                logger.critical("Critical error during local network setup!")
                return False
        else:
            logger.warning("Management Network is disabled, skipping setup.")
        
        if self.influx_db.store_disabled:
            logger.warning("InfluxDB experiment data storage is disabled!")
        elif self.influx_db.full_result_wrapper is not None:
            logger.info("InfluxDB is disabled, data points are stored in FullResultWrapper for API usage!")
        else:
            logger.success(f"Experiment data will be saved to InfluxDB {self.influx_db.database} with tag experiment={self.influx_db.series_name}")

        if not load_vm_initialization(self.provider.testbed_config, self.base_path, self.state_manager):
            logger.critical("Critical error while loading Instance initialization!")
            return False

        self.state_manager.assign_all_vsock_cids()

        if not self.start_management_infrastructure(self.pause_after != PauseAfterSteps.SETUP):
            logger.critical("Critical error during start of management infrastructure!")
            return False

        if not self.setup_infrastructure():
            logger.critical("Critical error during instance setup")
            return False

        setup_timeout = self.provider.testbed_config.settings.startup_init_timeout
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
                            instance.get_setup_env()[1]))
        else:
            logger.info("Waiting for Instances to start and initialize ...")

        if not self.wait_for_to_become(setup_timeout, "Instance Initialization", 
                                       AgentManagementState.INITIALIZED, 
                                       self.pause_after == PauseAfterSteps.INIT, True):
            return False

        logger.info("Instances are initialized, invoking installation of apps ...")
        for config_instance in self.provider.testbed_config.instances:
            instance = self.state_manager.get_instance(config_instance.name)
            apps = config_instance.applications
            instance.add_apps(apps)
            instance.set_state(AgentManagementState.APPS_SENDED)
            instance.send_message(InstallApplicationsMessageUpstream(apps))
        
        if not self.wait_for_to_become(setup_timeout, 'App Installation', 
                                AgentManagementState.APPS_READY, 
                                self.pause_after == PauseAfterSteps.INIT, True):
            return False
        
        logger.success("All Instances reported up & ready!")

        start_status = self.integration_helper.handle_stage_start(InvokeIntegrationAfter.INIT)
        if start_status is None:
            logger.debug(f"No integration scheduled for start at stage {InvokeIntegrationAfter.INIT}")
        elif start_status is False:
            logger.critical("Critical error during integration start!")
            return False

        if self.pause_after == PauseAfterSteps.INIT:
            if not self.start_interaction(PauseAfterSteps.INIT):
                self.send_finish_message()
                return True
        
        t0 = time.time() + self.provider.testbed_config.settings.appstart_timesync_offset

        logger.info(f"Starting applications on Instances (t0={t0}).")
        message = RunApplicationsMessageUpstream(t0)
        for instance in self.state_manager.get_all_instances():
            instance.send_message(message)
            instance.set_state(AgentManagementState.IN_EXPERIMENT)
            
        logger.info("Waiting for Instances to finish applications ...")

        experiment_timeout = self.provider.testbed_config.settings.experiment_timeout

        # Calculate by longest application
        if experiment_timeout == -1:
            experiment_timeout = self.app_dependencies.get_maximum_runtime()
            if experiment_timeout != 0:
                experiment_timeout *= 2
    
        if experiment_timeout == 0:
            logger.error("Maximum experiment duration could not be calculated -> No Applications or just daemons installed!")
            if self.pause_after == PauseAfterSteps.EXPERIMENT:
                self.start_interaction(PauseAfterSteps.EXPERIMENT)
            
            self.send_finish_message()
            return False
        else:
            succeeded = False

            if self.wait_for_to_become(experiment_timeout, 'Experiment', 
                                    AgentManagementState.FINISHED, 
                                    False, False):
                succeeded = True
                logger.success("All Instances reported finished applications!")
            
            if self.pause_after == PauseAfterSteps.EXPERIMENT:
                self.start_interaction(PauseAfterSteps.EXPERIMENT)
            
            self.send_finish_message()
            
            self.provider.result_wrapper.dump_state()
            return succeeded # Dismantling handled by main
