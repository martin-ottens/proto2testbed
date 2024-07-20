from enum import Enum
from typing import Tuple
from threading import Lock, Semaphore

class AgentManagementState(Enum):
    UNKNOWN = 0
    STARTED = 1
    INITIALIZED = 2
    IN_EXPERIMENT = 3
    FINISHED = 4
    DISMANTLE = 5
    FAILED = 99

class MachineState():
    def __init__(self, name: str, script_file: str, setup_env: dict[str, str], manager):
        self.name: str = name
        self.script_file: str = script_file
        self.setup_env = setup_env
        self.manager = manager

        self._state: AgentManagementState = AgentManagementState.UNKNOWN
        self.connection = None
        self.addr: Tuple[str, int] | None = None
    
    def get_setup_env(self) -> Tuple[str, dict[str, str]]:
        return self.script_file, self.setup_env
    
    def get_state(self) -> AgentManagementState:
        return self._state

    def set_state(self, new_state: AgentManagementState):
        if self._state == new_state:
            return
        
        self._state = new_state
        self.manager.notify_state_change(new_state)
    
    def connect(self, addr: Tuple[str, int], connection):
        self.addr = addr
        self.connection = connection
        self.set_state(AgentManagementState.STARTED)

    def disconnect(self):
        self.addr = None
        self.connection = None
        self.set_state(AgentManagementState.DISMANTLE)

class MachineStateManager():
    def __init__(self):
        self.map: dict[str, MachineState] = {}
        self.state_change_lock: Lock = Lock()

        self.waiting_for_state: MachineState | None = None
        self.state_change_semaphore: Semaphore | None = None
    
    def add_machine(self, name: str, script_file: str, setup_env: dict[str, str]):
        if name in self.map:
            raise Exception(f"Machine {name} was already configured")
        
        self.map[name] = MachineState(name, script_file, setup_env, self)
    
    def remove_machine(self, name: str):
        if not name in self.map:
            return
        self.map.pop(name).disconnect()

    def remove_all(self):
        for machine in self.map.values():
            machine.disconnect()
        
        self.map.clear()

    def get_machine(self, name: str) -> MachineState | None:
        if name not in self.map:
            return None
        
        return self.map[name]
    
    def send_machine_message(self, name: str, message: bytes):
        if name not in self.map:
            raise Exception(f"Machine {name} is not configured")
        
        connection = self.map[name].connection

        if connection is None:
            raise Exception(f"Machine {name} is not connected")
        
        connection.send_message(message)

    def all_machines_in_state(self, expected_state: AgentManagementState) -> bool:
        return all(x.get_state() == expected_state for x in self.map.values())
    
    def all_machines_connected(self) -> bool:
        return all(x.connection is not None for x in self.map.values())
    
    def notify_state_change(self, new_state: AgentManagementState):
        with self.state_change_lock:
            if self.state_change_semaphore is not None:
                if new_state == AgentManagementState.FAILED:
                    self.state_change_semaphore.release(n=len(self.map))
                    return

                if new_state == self.waiting_for_state:
                    self.state_change_semaphore.release()
    
    def wait_for_machines_to_become_state(self, expected_state: AgentManagementState, timeout = None) -> bool:
        wait_for_count = 0
        with self.state_change_lock:
            self.state_change_semaphore = Semaphore(0)
            self.waiting_for_state = expected_state
            wait_for_count = sum(map(lambda x: x.get_state() != expected_state, self.map.values()))
        
        for _ in range(wait_for_count):
            waited = self.state_change_semaphore.acquire(timeout=timeout)
        
        with self.state_change_lock:
            self.waiting_for_state = None
            self.state_change_semaphore = None

            if not waited:
                return False

            return sum(map(lambda x: x.get_state() == expected_state, self.map.values())) == len(self.map)