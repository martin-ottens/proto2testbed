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

from typing import Optional, List
from pathlib import Path

from utils.settings import TestbedConfig, RunParameters
from full_result_wrapper import FullResultWrapper
from utils.state_provider import TestbedStateProvider
from helper.export_helper import APISeriesContainer
from helper.state_file_helper import StateFileEntry
from cli import CLI

class Proto2TestbedAPI:
    def __init__(self, verbose: int = 0, sudo: bool = False, 
                 log_to_influx: bool = True) -> None:
        CLI.setup_early_logging()

        original_uid = os.environ.get("SUDO_UID", None)
        if original_uid is None:
            original_uid = os.getuid()

        self.testbed_config: Optional[TestbedConfig] = None
        self.experiment_tag: Optional[str] = None
        self.provider = TestbedStateProvider(basepath=Path(__file__).parent.resolve(),
                                             verbose=verbose,
                                             sudo=sudo,
                                             invoker=int(original_uid),
                                             from_api_call=True,
                                             cache_datapoints=(not log_to_influx))
        
        CLI(self.provider)

    def set_testbed_config(self, config: TestbedConfig) -> None:
        self.testbed_config = config

    def set_experiment_tag(self, tag: Optional[str]) -> None:
        self.experiment_tag = self.provider.update_experiment_tag(tag, False)

    def run_testbed(self, parameters: RunParameters) -> Optional[FullResultWrapper]:
        if self.testbed_config is None:
            raise ValueError("No testbed config is defined")
        
        if self.experiment_tag is None:
            raise ValueError("No experiment tag is defined")
        
        # TODO self.provider.update_experiment_tag(tag, False)
        # TODO self.provider.release_experiment_tag()

    def list_testbeds(self, from_all_users: bool = False) -> List[StateFileEntry]:
        from helper.state_file_helper import StateFileReader
        
        statefile_reader = StateFileReader(self.provider)
        return statefile_reader.get_states(filter_owned_by_executor=(not from_all_users))

    def export_results(self, additional_applications_path: Optional[str]) -> List[APISeriesContainer]:
        if self.testbed_config is None:
            raise ValueError("No testbed config defined")
        
        if self.experiment_tag is None:
            raise ValueError("No experiment tag is defined")

        from helper.export_helper import ResultExportHelper

        exporter = ResultExportHelper(self.testbed_config, additional_applications_path, self.provider)
        return exporter.output_to_list()

    def clean_results(self) -> None:
        pass
