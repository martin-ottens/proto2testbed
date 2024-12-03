from dataclasses import dataclass
from typing import List, Optional


@dataclass
class MachineStateFileInterfaceMapping():
    bridge_dev: str
    bridge_name: str
    tap_index: int
    tap_dev: str
    tap_mac: str


@dataclass
class MachineStateFile():
    instance: str
    executor: int
    cmdline: str
    experiment: str
    main_pid: int
    uuid: str
    mgmt_ip: Optional[str]
    interfaces: List[MachineStateFileInterfaceMapping]

@dataclass
class StateFileEntry:
    contents: MachineStateFile
    filepath: str

class StateFileReader():
    def __init__(self) -> None:
        pass

    def reload(self) -> None:
        pass

    def get_states(self, owned_by_executor: bool = False) -> List[StateFileEntry]:
        pass

    def get_states_experiment(self, experiment: str, 
                              owned_by_executor: bool = False) -> List[StateFileEntry]:
        pass

    def get_running_experiments(self, owned_by_executor: bool = False) -> List[str]:
        pass

    def get_dangling_states(self, owned_by_executor: bool = False) -> List[StateFileEntry]:
        pass 
