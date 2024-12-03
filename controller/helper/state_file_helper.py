import os
import json

from loguru import logger
from dataclasses import dataclass
from typing import List, Optional

from constants import INTERCHANGE_BASE_PATH, MACHINE_STATE_FILE
from utils.settings import CommonSettings

@dataclass
class MachineStateFileInterfaceMapping():
    bridge_dev: str
    bridge_name: str
    tap_index: int
    tap_dev: str
    tap_mac: str

    def __lt__(self, other) -> bool:
        return self.tap_index < other.tap_index


@dataclass
class MachineStateFile():
    instance: str
    executor: int
    cmdline: str
    experiment: str
    main_pid: int
    uuid: str
    mgmt_ip: Optional[str]
    interfaces: List[MachineStateFileInterfaceMapping] = None

    @staticmethod
    def from_json(json):
        interfaces = []
        for mapping in json["interfaces"]:
            interfaces.append(MachineStateFileInterfaceMapping(**mapping))

        del json["interfaces"]

        obj = MachineStateFile(**json)
        obj.interfaces = interfaces
        return obj


@dataclass
class StateFileEntry:
    contents: Optional[MachineStateFile]
    filepath: str


class StateFileReader():
    def __init__(self) -> None:
        self.files: List[StateFileEntry] = []
        self.reload()

    def reload(self) -> None:
        base_dir = os.path.dirname(INTERCHANGE_BASE_PATH)
        prefix = os.path.basename(INTERCHANGE_BASE_PATH)
        self.files = []
        if not os.path.exists(base_dir) or not os.path.isdir(base_dir):
            return
        
        for item in os.listdir(base_dir):
            itempath = os.path.join(base_dir, item)
            if not item.startswith(prefix) or not os.path.isdir(itempath):
                continue

            statefilepath = os.path.join(itempath, MACHINE_STATE_FILE)
            try:
                with open(statefilepath, "r") as handle:
                    state = MachineStateFile.from_json(json.load(handle))
                    self.files.append(StateFileEntry(state, statefilepath))
                    logger.trace(f"Loaded a state from '{statefilepath}'")
            except Exception as ex:
                logger.opt(exception=ex).debug(f"Cannot load state file '{statefilepath}'")
                self.files.append(StateFileEntry(None, statefilepath))

    @staticmethod
    def is_process_running(state: MachineStateFile) -> bool:
        import psutil
        try:
            proc = psutil.Process(state.main_pid)
            if proc is None:
                return False
            if not proc.is_running() or proc.status == psutil.STATUS_ZOMBIE:
                return False
            
            return state.cmdline in ' '.join(proc.cmdline())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def get_states(self, owned_by_executor: bool = False, 
                   experiment_tag: Optional[str] = None, 
                   running: Optional[bool] = None) -> List[StateFileEntry]:
        
        result: List[StateFileEntry] = []
        for state in self.files:
            if state.contents is None and (running is not None and not running):
                result.append(state)

            if owned_by_executor and state.contents.executor != CommonSettings.executor:
                continue

            if experiment_tag is not None and state.contents.experiment != CommonSettings.experiment:
                continue

            if running is not None:
                is_running = StateFileReader.is_process_running(state.contents)
                if is_running and running:
                    result.append(state)
                elif not is_running and not running:
                    result.append(state)
            else:
                result.append(state)
                
        return result

    def get_running_experiments(self, owned_by_executor: bool = False) -> List[str]:
        all = self.get_states(owned_by_executor=owned_by_executor, running=True)

        result: List[str] = []
        for item in all:
            if item.contents is None:
                continue

            result.append(item.contents.experiment)

