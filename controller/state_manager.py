import time
import random
import string
import os
import shutil

from enum import Enum
from pathlib import Path
from loguru import logger
from typing import Tuple, Optional, List
from threading import Lock, Semaphore, Event

from utils.system_commands import invoke_subprocess
from helper.file_copy_helper import FileCopyHelper
from helper.network_helper import BridgeMapping
from common.application_configs import ApplicationConfig

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

class MachineState():
    __INTERCHANGE_BASE_PATH = "/tmp/ptb-i-"

    def __init__(self, name: str, script_file: str, 
                 setup_env: Optional[dict[str, str]], manager,):
        self.name: str = name
        self.script_file: str = script_file
        self.uuid = ''.join(random.choices(string.ascii_letters, k=8))
        
        if setup_env == None:
            self.setup_env = {}
        else:
            self.setup_env = setup_env
        
        self.manager = manager

        self._state: AgentManagementState = AgentManagementState.UNKNOWN
        self.connection = None
        self.interchange_ready = False
        self.interfaces_hostside: List[BridgeMapping] = []
        self.preserve_files: List[str] = []
        self.apps = Optional[List[ApplicationConfig]]
        self.mgmt_ip_addr: Optional[str] = None
        self.file_copy_helper = FileCopyHelper(self)

    def __str__(self) -> str:
        return f"{self.name} ({self.uuid})"

    def add_preserve_file(self, file: str):
        self.preserve_files.append(file)

    def add_interface(self, interface: BridgeMapping):
        self.interfaces_hostside.append(interface)
    
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
        self.interchange_dir = Path(MachineState.__INTERCHANGE_BASE_PATH + self.uuid + "/")

        if self.interchange_dir.exists():
            raise Exception(f"Error during setup of interchange directory: {self.interchange_dir} already exists!")
        
        # Set 777 permission to allow socket access with --sudo option
        os.mkdir(self.interchange_dir, mode=0o777)
        os.mkdir(self.interchange_dir / "mount/")
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
                logger.info(f"File Preservation: Preserved {len(flist)} files for Instance {self.name} to '{target}'")
            
        
        shutil.rmtree(self.interchange_dir)
        self.interchange_ready = False

    def get_mgmt_socket_path(self) -> None | Path:
        if not self.interchange_ready:
            return None
        return self.interchange_dir / "mgmt.sock"
    
    def get_mgmt_tty_path(self) -> None | Path:
        if not self.interchange_ready:
            return None
        return self.interchange_dir / "tty.sock"
    
    def get_p9_data_path(self) -> None | Path:
        if not self.interchange_ready:
            return None
        return self.interchange_dir / "mount/"
    
    def update_mgmt_socket_permission(self) -> bool:
        if not self.interchange_ready:
            return False
        
        wait_until = time.time() + 20
        while time.time() <= wait_until:
            if os.path.exists(self.get_mgmt_socket_path()) and os.path.exists(self.get_mgmt_tty_path()):
                process = invoke_subprocess(["chmod", "777", str(self.get_mgmt_socket_path())], needs_root=True)

                if process.returncode != 0:
                    raise Exception("Unable to change permissions of management server socket")
                
                process = invoke_subprocess(["chmod", "777", str(self.get_mgmt_tty_path())], needs_root=True)

                if process.returncode != 0:
                    raise Exception("Unable to change permissions of management tty socket")

                return True

            time.sleep(1)
        
        return False

    def send_message(self, message: bytes):
        if self.connection is None:
            raise Exception(f"Machine {self.name} is not connected")

        self.connection.send_message(message)
    
    def connect(self, connection):
        self.connection = connection

        if self.get_state() != AgentManagementState.DISCONNECTED:
            self.set_state(AgentManagementState.STARTED)

    def disconnect(self):
        self.connection = None
        self.set_state(AgentManagementState.DISCONNECTED)

class MachineStateManager():
    def __init__(self):
        self.map: dict[str, MachineState] = {}
        self.state_change_lock: Lock = Lock()
        self.file_preservation: Optional[Path] = None

        self.waiting_for_state: MachineState | None = None
        self.state_change_semaphore: Semaphore | None = None
        self.has_shutdown_signal = Event()
        self.has_shutdown_signal.clear()

    def enable_file_preservation(self, preservation_path: Optional[Path]):
        self.file_preservation = preservation_path

    def get_all_machines(self) -> List[MachineState]:
        return list(self.map.values())
    
    def add_machine(self, name: str, script_file: str, 
                    setup_env: dict[str, str]):
        if name in self.map:
            raise Exception(f"Machine {name} was already configured")
        
        self.map[name] = MachineState(name, script_file, setup_env, self)
        self.map[name].set_setup_env_entry("INSTANCE_NAME", name)
    
    def remove_machine(self, name: str):
        if not name in self.map:
            return
        self.map.pop(name).disconnect()

    def remove_all(self):
        for machine in self.map.values():
            machine.remove_interchange_dir(self.file_preservation)
            machine.disconnect()
        
        self.map.clear()

    def get_machine(self, name: str) -> MachineState | None:
        if name not in self.map:
            return None
        
        return self.map[name]
    
    def send_machine_message(self, name: str, message: bytes):
        if name not in self.map:
            raise Exception(f"Machine {name} is not configured")
        
        machine = self.map[name]
        machine.send_message(message)

    def all_machines_in_state(self, expected_state: AgentManagementState) -> bool:
        return all(x.get_state() == expected_state for x in self.map.values())
    
    def all_machines_connected(self) -> bool:
        return all(x.connection is not None for x in self.map.values())
    
    def apply_shutdown_signal(self):
        with self.state_change_lock:
            self.has_shutdown_signal.set()

            if self.state_change_semaphore is not None:
                self.state_change_semaphore.release(n=len(self.map))
            
    
    def notify_state_change(self, new_state: AgentManagementState):
        with self.state_change_lock:
            if self.state_change_semaphore is not None:
                if new_state == AgentManagementState.FAILED:
                    self.state_change_semaphore.release(n=len(self.map))
                    return

                if new_state == self.waiting_for_state:
                    self.state_change_semaphore.release()
    
    def wait_for_machines_to_become_state(self, expected_state: AgentManagementState, timeout = None) -> WaitResult:
        wait_for_count = 0
        with self.state_change_lock:
            self.state_change_semaphore = Semaphore(0)
            self.waiting_for_state = expected_state
            wait_for_count = sum(map(lambda x: x.get_state() != expected_state, self.map.values()))
        
        wait_until = time.time() + timeout
        for _ in range(wait_for_count):
            try:
                this_run_time = time.time()
                if this_run_time >= wait_until:
                    waited = False
                    continue

                waited = self.state_change_semaphore.acquire(timeout=(wait_until - this_run_time))
            except InterruptedError:
                self.waiting_for_state = None
                self.state_change_semaphore = None
                return WaitResult.INTERRUPTED
        
        with self.state_change_lock:
            self.waiting_for_state = None
            self.state_change_semaphore = None

            if not waited:
                return WaitResult.TIMEOUT
            
            if self.has_shutdown_signal.is_set():
                self.has_shutdown_signal.clear()
                return WaitResult.SHUTDOWN

            if sum(map(lambda x: x.get_state() == expected_state, self.map.values())) == len(self.map):
                return WaitResult.OK
            else:
                return WaitResult.FAILED
