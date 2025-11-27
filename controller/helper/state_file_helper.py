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

import os
import jsonpickle

from loguru import logger
from dataclasses import dataclass
from typing import List, Optional, Dict
from pathlib import Path

from constants import MACHINE_STATE_FILE, INTERCHANGE_DIR_PREFIX, EXPERIMENT_RESERVATION_DIR
from utils.networking import InstanceInterface
from utils.state_lock import StateLock


@dataclass
class InstanceStateFile:
    instance: str
    executor: int
    cmdline: str
    main_pid: int
    uuid: str
    mgmt_ip: Optional[str]
    experiment: str = None
    interfaces: Optional[List[InstanceInterface]] = None

    @staticmethod
    def from_json(json_str : str):
        obj: InstanceStateFile = jsonpickle.decode(json_str)

        if obj.interfaces:
            for interface in obj.interfaces:
                status = interface.check_export_values()
                if status is not None:
                    raise Exception(f"Invalid interface class while parsing state files: {status}")

        return obj


@dataclass
class StateFileEntry:
    contents: Optional[InstanceStateFile]
    unique_run_name: str
    filepath: str


class StateFileReader:
    def __init__(self, provider) -> None:
        self.provider = provider
        self.files: List[StateFileEntry] = []

        # unique_run_name -> experiment_tag
        self.experiment_map: Dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        base_dir = self.provider.statefile_base
        self.files = []
        self.experiment_map = {}

        if not os.path.exists(base_dir) or not os.path.isdir(base_dir):
            return
        
        experiment_dir = os.path.join(base_dir, EXPERIMENT_RESERVATION_DIR)
        if os.path.exists(experiment_dir) and os.path.isdir(experiment_dir):
            for experiment in os.listdir(experiment_dir):
                with open(os.path.join(experiment_dir, experiment), "r") as handle:
                    unique_run_name = handle.readline()
                self.experiment_map[unique_run_name] = experiment

        for unique_run_name in os.listdir(base_dir):
            if not os.path.isdir(os.path.join(base_dir, unique_run_name)):
                continue

            for instance in os.listdir(os.path.join(base_dir, unique_run_name)):
                if not instance.startswith(INTERCHANGE_DIR_PREFIX):
                    continue

                itempath = os.path.join(base_dir, unique_run_name, instance)
                if not os.path.isdir(itempath):
                    continue

                statefilepath = os.path.join(itempath, MACHINE_STATE_FILE)
                if not os.path.exists(statefilepath):
                    continue

                try:
                    with open(statefilepath, "r") as handle:
                        state = InstanceStateFile.from_json(handle.read())

                        experiment = self.experiment_map.get(unique_run_name, None)
                        state.experiment = experiment

                        self.files.append(StateFileEntry(state, unique_run_name, statefilepath))
                        logger.trace(f"Loaded a state from '{statefilepath}'")
                except Exception as ex:
                    logger.opt(exception=ex).error(f"Cannot load state file '{statefilepath}'")
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
    def is_process_running(state: InstanceStateFile) -> bool:
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
        
    @staticmethod
    def check_and_aquire_experiment(lock: StateLock, tag: str, basedir: str,
                                    uniqe_run_name: str) -> bool:
        experiment_dir = Path(basedir) / EXPERIMENT_RESERVATION_DIR
        os.makedirs(experiment_dir, mode=0o777, exist_ok=True)
        with lock:
            for item in os.listdir(experiment_dir):
                if tag == item:
                    return False
                
            fd = os.open(experiment_dir / tag, os.O_WRONLY | os.O_CREAT, 0o777)
            with open(fd, "w") as handle:
                handle.write(uniqe_run_name)
        return True
        
    @staticmethod
    def release_experiment(lock: StateLock, tag: str, basedir: str) -> None:
        with lock:
            try:
                os.remove(Path(basedir) / EXPERIMENT_RESERVATION_DIR / tag)
            except Exception as ex:
                logger.opt(exception=ex).error("Unable to release experiment tag mapping")

    def get_states(self, filter_owned_by_executor: bool = False, 
                   filter_experiment_tag: Optional[str] = None, 
                   filter_running: Optional[bool] = None) -> List[StateFileEntry]:

        result: List[StateFileEntry] = []
        for state in self.files:
            if state.contents is None and (filter_running is not None and not filter_running):
                result.append(state)

            if filter_owned_by_executor and state.contents.executor != self.provider.executor:
                continue

            if filter_experiment_tag is not None and state.contents.experiment != self.provider.experiment:
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
        all_states = self.get_states(filter_owned_by_executor=False,
                                     filter_experiment_tag=experiment_tag,
                                     filter_running=True)
        
        result = {}
        for entry in all_states:
            ui = StateFileReader.get_name(entry.contents.executor)
            if ui not in result.keys():
                result[ui] = entry.contents.main_pid
        
        return result

    def get_running_experiments(self, filter_owned_by_executor: bool = False) -> List[str]:
        all_states = self.get_states(filter_owned_by_executor=filter_owned_by_executor, filter_running=True)

        result: List[str] = []
        for item in all_states:
            if item.contents is None:
                continue

            result.append(item.contents.experiment)

        return result
    
    def free_unused_experiment_tags(self):
        delete_keys = []
        for key, value in self.experiment_map.items():
            found = False

            for entry in self.files:
                if key == entry.unique_run_name:
                    found = True
                    break
            
            if not found:
                delete_keys.append(key)
            else:
                logger.trace(f"Testbed '{key}' for experiment tag '{value}' is still running.")

        for delete_key in delete_keys:
            logger.debug(f"Deleting unused experiment tag '{self.experiment_map[delete_key]}' for non-existing testbed '{delete_key}'")
            try:
                os.remove(Path(self.provider.statefile_base) / EXPERIMENT_RESERVATION_DIR / value)
                del self.experiment_map[delete_key]
            except Exception as ex:
                logger.opt(exception=ex).error("Cannot deleting experiment tag mapping file")
