#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2025 Martin Ottens
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
import psutil
import random
import string

from pathlib import Path
from typing import Optional

from utils.settings import DefaultConfigs, TestbedConfig
from helper.state_file_helper import StateFileReader
from utils.concurrency_reservation import ConcurrencyReservation
from utils.state_lock import StateLock
from state_manager import InstanceStateManager
from cli import CLI
from full_result_wrapper import FullResultWrapper
from constants import DEFAULT_CONFIG_PATH, DEFAULT_STATE_DIR
from utils.config_tools import check_preserve_dir


class TestbedStateProvider:
    def __init__(self, verbose: int, sudo: bool, 
                 from_api_call: bool = False, cache_datapoints: bool = False, 
                 preserve: Optional[Path] = None) -> None:

        self.default_configs = DefaultConfigs(DEFAULT_CONFIG_PATH)
        self.statefile_base = Path(self.default_configs.get_defaults("statefile_basedir", DEFAULT_STATE_DIR))
        
        original_uid = os.environ.get("SUDO_UID", None)
        if original_uid is None:
            original_uid = os.getuid()
        
        self.executor = int(original_uid)
        self.main_pid = os.getpid()
        self.cmdline = " ".join(psutil.Process(self.main_pid).cmdline())
        self.app_base_path = Path(__file__).parent.parent.resolve()
        self.log_verbose = verbose
        self.sudo_mode = sudo
        self.experiment: Optional[str] = None
        self.experiment_generated = False
        self.preserve: Optional[Path] = preserve
        self.unique_run_name = f"{self.main_pid}-{self.executor}"
        self.testbed_config: Optional[TestbedConfig] = None
        self.concurrency_reservation: Optional[ConcurrencyReservation] = None
        self.state_lock = StateLock(self.statefile_base)
        self.from_api_call = from_api_call
        self.cache_datapoints = cache_datapoints
        self.cli: Optional[CLI] = None
        self.instance_manager: Optional[InstanceStateManager] = None
        self.result_wrapper: Optional[FullResultWrapper] = None
        self.snapshots_enabled: bool = False
    
    def update_experiment_tag(self, experiment: Optional[str], accuire: bool) -> str:
        if self.experiment is not None and accuire:
            self.release_experiment_tag()

        if experiment is not None and accuire:
            if not StateFileReader.check_and_aquire_experiment(self.state_lock, 
                                                               experiment, 
                                                               self.statefile_base):
                raise Exception(f"Experiment tag must be unique, but {experiment} is already in use!")
            
            self.experiment = experiment
            self.concurrency_reservation = ConcurrencyReservation(self)
            return self.experiment
        else:
            self.experiment = experiment
            while self.experiment is None:
                self.experiment = "".join(random.choices(string.ascii_letters + string.digits, k=8))
                self.experiment_generated = True

                if accuire and not StateFileReader.check_and_aquire_experiment(self.state_lock, 
                                                                               self.experiment, 
                                                                               self.statefile_base):
                    self.experiment = None
            
            self.concurrency_reservation = ConcurrencyReservation(self)
            return self.experiment
        
    def update_preserve_path(self, preserve_path: Optional[Path]) -> bool:
        if not check_preserve_dir(preserve_path, self.executor):
            return False
        
        self.preserve = preserve_path
        return True

    def set_snapshots_enabled(self, enabled: bool) -> None:
        self.snapshots_enabled = enabled

    def release_experiment_tag(self) -> None:
        StateFileReader.release_experiment(self.state_lock, 
                                           self.experiment, 
                                           self.statefile_base)
        self.experiment = None
        self.experiment_generated = False
        self.concurrency_reservation = None

    def set_testbed_config(self, config: TestbedConfig) -> None:
        self.testbed_config = config

    def set_cli(self, cli: CLI) -> None:
        self.cli = cli

    def set_instance_manager(self, instance_manager: InstanceStateManager) -> None:
        self.instance_manager = instance_manager

    def set_full_result_wrapper(self, result_wrapper: FullResultWrapper) -> None:
        self.result_wrapper = result_wrapper
