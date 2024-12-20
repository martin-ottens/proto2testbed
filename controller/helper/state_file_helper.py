#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2024 Martin Ottens
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

import os
import json

from loguru import logger
from dataclasses import dataclass
from typing import List, Optional, Dict

from constants import INTERCHANGE_BASE_PATH, MACHINE_STATE_FILE
from utils.settings import CommonSettings
from utils.networking import InstanceInterface

@dataclass
class MachineStateFile():
    instance: str
    executor: int
    cmdline: str
    experiment: str
    main_pid: int
    uuid: str
    mgmt_ip: Optional[str]
    interfaces: Optional[List[InstanceInterface]] = None

    @staticmethod
    def from_json(json):
        interfaces = []
        for mapping in json["interfaces"]:
            interfaces.append(InstanceInterface(**mapping))

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
    def get_name(uid: int) -> str:
        import pwd
        try:
            ui = pwd.getpwuid(uid)
            return ui.pw_name
        except KeyError:
            return str(uid)

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

    def get_states(self, filter_owned_by_executor: bool = False, 
                   filter_experiment_tag: Optional[str] = None, 
                   filter_running: Optional[bool] = None) -> List[StateFileEntry]:
        
        result: List[StateFileEntry] = []
        for state in self.files:
            if state.contents is None and (filter_running is not None and not filter_running):
                result.append(state)

            if filter_owned_by_executor and state.contents.executor != CommonSettings.executor:
                continue

            if filter_experiment_tag is not None and state.contents.experiment != CommonSettings.experiment:
                continue

            if filter_running is not None:
                is_running = StateFileReader.is_process_running(state.contents)
                if is_running and filter_running:
                    result.append(state)
                elif not is_running and not filter_running:
                    result.append(state)
            else:
                result.append(state)
                
        return result

    def get_other_experiments(self, experiment_tag: str) -> Dict[str, int]:
        all = self.get_states(filter_owned_by_executor=False,
                              filter_experiment_tag=experiment_tag,
                              filter_running=True)
        
        result = {}
        for entry in all:
            ui = StateFileReader.get_name(entry.contents.executor)
            if ui not in result.keys():
                result[ui] = entry.contents.main_pid
        
        return result

    def get_running_experiments(self, filter_owned_by_executor: bool = False) -> List[str]:
        all = self.get_states(filter_owned_by_executor=filter_owned_by_executor, running=True)

        result: List[str] = []
        for item in all:
            if item.contents is None:
                continue

            result.append(item.contents.experiment)

