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

import time
import random
import string
import os
import shutil
import json
import socket
import errno

from enum import Enum
from pathlib import Path
from loguru import logger
from typing import Tuple, Optional, List, Dict, Any
from threading import Lock, Semaphore, Event

from utils.system_commands import invoke_subprocess, set_owner
from helper.file_copy_helper import FileCopyHelper
from helper.app_dependency_helper import AppDependencyHelper
from utils.networking import InstanceInterface
from helper.state_file_helper import InstanceStateFile
from common.application_configs import ApplicationConfig, AppStartStatus
from common.instance_manager_message import UpstreamMessage, ApplicationStatusMessageUpstream
from utils.interfaces import Dismantable
from common.interfaces import DataclassJSONEncoder
from utils.settings import CommonSettings
from constants import *


class AgentManagementState(Enum):
    UNKNOWN = 0
    STARTED = 1
    INITIALIZED = 2
    APPS_SENDED = 3
    APPS_READY = 4
    IN_EXPERIMENT = 5
    FINISHED = 6
    FILES_PRESERVED = 7
    DISCONNECTED = 8
    FAILED = 99


class WaitResult(Enum):
    OK = 0
    FAILED = 1
    TIMEOUT = 2
    INTERRUPTED = 3
    SHUTDOWN = 4


class InstanceState:
    @staticmethod
    def clean_interchange_dir(path: str) -> bool:
        prefix = INTERCHANGE_BASE_PATH
        try:
            if os.path.isdir(path) and path.startswith(prefix):
                shutil.rmtree(path)
                return True
            else:
                logger.debug(f"Skipping deletion of '{path}': Not a directory or invalid name.")
                return False
        except Exception as ex:
            logger.opt(exception=ex).error(f"Error deleting interchange directory '{path}'")
            return False

    def __init__(self, name: str, script_file: str, 
                 setup_env: Optional[Dict[str, str]], manager,
                 init_preserve_files: Optional[List[str]], numeric_id: int,
                 enable_vsock: bool = False) -> None:
        self.name: str = name
        self.script_file: str = script_file
        self.uuid = ''.join(random.choices(string.ascii_letters, k=8))
        self.numeric_id = numeric_id
        self.interchange_dir = None
        self.vsock_enabled = enable_vsock
        self.vsock_cid: Optional[int] = None
        
        if setup_env is None:
            self.setup_env = {}
        else:
            self.setup_env = setup_env
        
        self.manager = manager

        self._state: AgentManagementState = AgentManagementState.UNKNOWN
        self.connection = None
        self.interchange_ready = False
        self.interfaces: List[InstanceInterface] = []
        if init_preserve_files is not None:
            self.preserve_files = init_preserve_files.copy()
        else:
            self.preserve_files: List[str] = []
        self.apps = Optional[List[ApplicationConfig]]
        self.mgmt_ip_addr: Optional[str] = None
        self.file_copy_helper = FileCopyHelper(self)

    def __str__(self) -> str:
        return f"{self.name} ({self.uuid})"

    def add_preserve_file(self, file: str):
        self.preserve_files.append(file)

    def add_interface_mapping(self, interface: InstanceInterface):
        self.interfaces.append(interface)

    def get_interface_by_bridge_name(self, bridge_name: str) -> Optional[InstanceInterface]:
        found_interface = None
        for interface in self.interfaces:
            if interface.bridge_name == bridge_name:
                found_interface = interface
                break
        
        return found_interface
    
    def get_interface_by_bridge_dev(self, bridge_dev: str) -> Optional[InstanceInterface]:
        found_interface = None
        for interface in self.interfaces:
            if interface.bridge_dev == bridge_dev:
                found_interface = interface
                break
        
        return found_interface

    def get_interface_by_tap_dev(self, tap_dev: str) -> Optional[InstanceInterface]:
        found_interface = None
        for interface in self.interfaces:
            if interface.tap_dev == tap_dev:
                found_interface = interface
                break
        
        return found_interface

    def set_interface_bridge_attached(self, tap_dev: str) -> None:
        mapping = self.get_interface_by_tap_dev(tap_dev)
        
        if mapping is None:
            raise Exception(f"Unable to find interface mapping for tap device '{tap_dev}'")

        mapping.bridge_attached = True
    
    def generate_vsock_cid(self) -> Optional[int]:
        if not self.vsock_enabled:
            return None
        
        if self.vsock_cid is not None:
            return self.vsock_cid

        potential_cid = os.getpid() + self.numeric_id
        if os.getpid() < 100:
            logger.trace("Probably running inside a container, using non-PID based initital VSOCK CID")
            potential_cid = random.randint(3, 0xFFFFFFFF)

        while True:
            s = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
            s.settimeout(0.1)
            try:
                s.connect((potential_cid, 1))
                s.close()
                logger.debug(f"Searching VSOCK CID for '{self.name}': Connection succeeded with CID {potential_cid}, looking for new one")
            except OSError as ex:
                if ex.errno in (errno.ENODEV, errno.EHOSTUNREACH):
                    self.vsock_cid = potential_cid
                    logger.trace(f"Using VSOCK CID {self.vsock_cid} for Instance '{self.name}'")
                    return potential_cid
            except Exception:
                logger.debug(f"Searching VSOCK CID for '{self.name}': Error using CID {potential_cid}: {ex}, in use?")
            
            potential_cid = random.randint(3, 0xFFFFFFFF)

    
    def set_mgmt_ip(self, ip_addr: str):
        self.mgmt_ip_addr = ip_addr
    
    def get_setup_env(self) -> Tuple[str, dict[str, str]]:
        return self.script_file, self.setup_env
    
    def set_setup_env_entry(self, key: str, value: str):
        self.setup_env[key] = value
    
    def get_state(self) -> AgentManagementState:
        return self._state
    
    def add_apps(self, apps: Optional[List[ApplicationConfig]]):
        self.apps = apps

    def set_state(self, new_state: AgentManagementState):
        if self._state == new_state:
            return
        
        self._state = new_state
        self.manager.notify_state_change(new_state)

    def prepare_interchange_dir(self) -> None:
        self.interchange_dir = Path(INTERCHANGE_BASE_PATH + self.uuid + "/")

        if self.interchange_dir.exists():
            raise Exception(f"Error during setup of interchange directory: {self.interchange_dir} already exists!")
        
        # Set 777 permission to allow socket access with --sudo option
        os.mkdir(self.interchange_dir, mode=0o777)
        os.mkdir(self.interchange_dir / INSTANCE_INTERCHANGE_DIR_MOUNT)
        self.interchange_ready = True

    def remove_interchange_dir(self, file_preservation: Optional[Path]) -> None:
        if not self.interchange_ready:
            return
        
        if file_preservation is not None:
            # Clean pending copy jobs, so that they are not copied to the testbed results
            if self.file_copy_helper is not None:
                self.file_copy_helper.clean_mount()

            flist = []
            for _, _, files in os.walk(self.get_p9_data_path()):
                for file in files:
                    flist.append(file)

            if len(flist) != 0:
                target = file_preservation / self.name
                target.mkdir(parents=True, exist_ok=True)
                shutil.copytree(self.get_p9_data_path(), target, dirs_exist_ok=True)
                if CommonSettings.executor is not None:
                    set_owner(target, CommonSettings.executor)
                logger.info(f"File Preservation: Preserved {len(flist)} files for Instance {self.name} to '{target}'")
            
        
        shutil.rmtree(self.interchange_dir)
        self.interchange_ready = False

    def get_mgmt_socket_path(self) -> None | Path:
        if not self.interchange_ready or self.vsock_enabled:
            return None
        return self.interchange_dir / INSTANCE_MANAGEMENT_SOCKET_PATH
    
    def get_mgmt_tty_path(self) -> None | Path:
        if not self.interchange_ready:
            return None
        return self.interchange_dir / INSTANCE_TTY_SOCKET_PATH
    
    def get_p9_data_path(self) -> None | Path:
        if not self.interchange_ready:
            return None
        return self.interchange_dir / INSTANCE_INTERCHANGE_DIR_MOUNT
    
    def update_mgmt_socket_permission(self) -> bool:
        if not self.interchange_ready:
            return False
        
        scope_sockets = [self.get_mgmt_tty_path()]
        if not self.vsock_enabled:
            scope_sockets.append(self.get_mgmt_socket_path())
        
        wait_until = time.time() + 20
        while time.time() <= wait_until:
            for scope in scope_sockets:
                if os.path.exists(scope):
                    process = invoke_subprocess(["chmod", "777", str(scope)], needs_root=True)

                    if process.returncode != 0:
                        raise Exception(f"Unable to change permissions of socket {scope}")
                
                scope_sockets = [x for x in scope_sockets if x != scope]

                if len(scope_sockets) == 0:
                    return True

            time.sleep(1)
        
        return False

    def send_message(self, message: UpstreamMessage) -> None:
        if self.connection is None:
            raise Exception(f"Instance {self.name} is not connected")

        self.connection.send_message(message)

    def is_connected(self) -> bool:
        return self.connection is not None
    
    def connect(self, connection) -> None:
        self.connection = connection

        if self.get_state() != AgentManagementState.DISCONNECTED:
            self.set_state(AgentManagementState.STARTED)

    def disconnect(self) -> None:
        self.connection = None
        self.set_state(AgentManagementState.DISCONNECTED)

    def dump_state(self) -> None:
        dump_interfaces: List[Any] = []

        for interface in self.interfaces:
            dump_interfaces.append(interface.dump())

        state = InstanceStateFile(
            instance=self.name,
            uuid=self.uuid,
            executor=int(CommonSettings.executor),
            cmdline=CommonSettings.cmdline,
            experiment=CommonSettings.experiment,
            main_pid=CommonSettings.main_pid,
            mgmt_ip=str(self.mgmt_ip_addr),
            interfaces=dump_interfaces
        )

        target = self.interchange_dir / MACHINE_STATE_FILE
        with open(target, "w") as handle:
            json.dump(state, handle, cls=DataclassJSONEncoder, indent=4)

        logger.trace(f"Dumped state of Instance {self.name} to file {target}.")


class InstanceStateManager(Dismantable):
    def __init__(self, enable_vsock: bool = False) -> None:
        self.map: dict[str, InstanceState] = {}
        self.state_change_lock: Lock = Lock()
        self.file_preservation: Optional[Path] = None

        self.waiting_for_states: Optional[List[InstanceState]] = None
        self.state_change_semaphore: Optional[Semaphore] = None
        self.has_shutdown_signal = Event()
        self.has_shutdown_signal.clear()
        self.external_interrupt_signal = Event()
        self.external_interrupt_signal.clear()
        self.instance_counter: int = 0
        self.enable_vsock = enable_vsock
        self.app_dependecy_helper: Optional[AppDependencyHelper] = None

    def set_app_dependecy_helper(self, helper: AppDependencyHelper) -> None:
        self.app_dependecy_helper = helper

    def enable_file_preservation(self, preservation_path: Optional[Path]):
        self.file_preservation = preservation_path

    def get_all_instances(self) -> List[InstanceState]:
        return list(self.map.values())
    
    def add_instance(self, name: str, script_file: str, 
                    setup_env: Dict[str, str], 
                    init_preserve_files: Optional[List[str]] = None):
        if name in self.map:
            raise Exception(f"Instance {name} was already configured")
        
        instance = InstanceState(name=name, 
                                 script_file=script_file, 
                                 setup_env=setup_env, 
                                 manager=self, 
                                 init_preserve_files=init_preserve_files, 
                                 numeric_id=self.instance_counter,
                                 enable_vsock=self.enable_vsock)

        instance.set_setup_env_entry("INSTANCE_NAME", name)
        self.instance_counter += 1
        self.map[name] = instance

    def dump_states(self) -> None:
        for instance in self.map.values():
            try:
                instance.dump_state()
            except Exception as ex:
                logger.opt(exception=ex).error(f"Unable to dump state of instance {instance.name}.")
    
    def remove_instance(self, name: str):
        if not name in self.map:
            return
        self.map.pop(name).disconnect()

    def report_app_state_change(self, reporting_instance: str, 
                                reporting_app: str, state: AppStartStatus) -> None:
        if self.app_dependecy_helper is None:
            raise Exception("AppDependencyHelper was not set!")
        
        for fulfilled_dependency in self.app_dependecy_helper.get_next_applications(reporting_instance, reporting_app, state):
            if fulfilled_dependency.instance not in self.map.keys():
                logger.error(f"Unable to invoke deferred Application {fulfilled_dependency.application.name}: Instance {fulfilled_dependency.instance} not found!")
                continue

            instance = self.map[fulfilled_dependency.instance]
            message = ApplicationStatusMessageUpstream(fulfilled_dependency.application.name, state)
            instance.send_message(message)
            logger.debug(f"Sending Application status update for '{fulfilled_dependency.application.name}' and state '{state}' to Instance '{fulfilled_dependency.instance}'.")

    def remove_all(self):
        if self.state_change_semaphore is not None and len(self.map) != 0:
            self.external_interrupt_signal.set()
            self.state_change_semaphore.release(n=len(self.map))

        for instance in self.map.values():
            instance.remove_interchange_dir(self.file_preservation)
            instance.disconnect()
        
        self.map.clear()

    def get_instance(self, name: str) -> Optional[InstanceState]:
        if name not in self.map.keys():
            return None
        
        return self.map[name]
    
    def send_instance_message(self, name: str,
                              message: UpstreamMessage) -> None:
        if name not in self.map:
            raise Exception(f"Instance {name} is not configured")
        
        instance = self.map[name]
        instance.send_message(message)

    def all_instances_in_state(self, expected_state: AgentManagementState) -> bool:
        return all(x.get_state() == expected_state for x in self.map.values())
    
    def all_instances_connected(self) -> bool:
        return all(x.connection is not None for x in self.map.values())
    
    def apply_shutdown_signal(self) -> None:
        with self.state_change_lock:
            self.has_shutdown_signal.set()

            if self.state_change_semaphore is not None:
                self.state_change_semaphore.release(n=len(self.map))
            
    
    def notify_state_change(self, new_state: AgentManagementState) -> None:
        with self.state_change_lock:
            if self.state_change_semaphore is not None:
                if new_state == AgentManagementState.FAILED:
                    self.state_change_semaphore.release(n=len(self.map))
                    return

                if new_state in self.waiting_for_states:
                    self.state_change_semaphore.release()
    
    def wait_for_instances_to_become_state(self, expected_states: List[AgentManagementState], 
                                          timeout = None) -> WaitResult:
        waited = False
        wait_for_count = 0
        with self.state_change_lock:
            self.state_change_semaphore = Semaphore(0)
            self.waiting_for_states = expected_states
            wait_for_count = sum(map(lambda x: x.get_state() not in expected_states, self.map.values()))
        
        wait_until = time.time() + timeout
        for _ in range(wait_for_count):
            try:
                this_run_time = time.time()
                if this_run_time >= wait_until:
                    waited = False
                    continue

                waited = self.state_change_semaphore.acquire(timeout=(wait_until - this_run_time))
            except Exception as ex:
                logger.opt(exception=ex).debug("Exception while waiting for Instances")
                self.waiting_for_state = None
                self.state_change_semaphore = None
                return WaitResult.INTERRUPTED

        with self.state_change_lock:
            self.waiting_for_states = None
            self.state_change_semaphore = None

            if self.external_interrupt_signal.is_set():
                return WaitResult.INTERRUPTED

            if not waited:
                return WaitResult.TIMEOUT
            
            if self.has_shutdown_signal.is_set():
                self.has_shutdown_signal.clear()
                return WaitResult.SHUTDOWN

            if sum(map(lambda x: x.get_state() in expected_states, self.map.values())) == len(self.map):
                return WaitResult.OK
            else:
                return WaitResult.FAILED
            
    def get_name(self) -> str:
        return "InstanceStateManager"
    
    def dismantle(self, force = False) -> None:
        self.remove_all()
    
    def dismantle_parallel(self) -> bool:
        return True
