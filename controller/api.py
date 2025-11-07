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

from typing import Optional, List

from utils.settings import TestbedConfig, RunParameters
from full_result_wrapper import FullResultWrapper
from utils.state_provider import TestbedStateProvider
from helper.export_helper import APISeriesContainer
from helper.state_file_helper import StateFileEntry
from cli import CLI

class Proto2TestbedAPI:
    def __init__(self, verbose: int = 0, sudo: bool = False, 
                 log_to_influx: bool = True) -> None:
        if verbose not in [0, 1, 2]:
            raise ValueError("Inavlid verbose mode, select from 0, 1, 2.")

        CLI.setup_early_logging()

        self.testbed_config: Optional[TestbedConfig] = None
        self.experiment_tag: Optional[str] = None
        self.provider = TestbedStateProvider(verbose=verbose,
                                             sudo=sudo,
                                             from_api_call=True,
                                             cache_datapoints=(not log_to_influx))
        
        CLI(self.provider)

    def set_testbed_config(self, config: TestbedConfig) -> None:
        self.testbed_config = config

    def set_experiment_tag(self, tag: Optional[str]) -> None:
        self.experiment_tag = tag

    def run_testbed(self, parameters: RunParameters, 
                    testbed_package_path: str) -> Optional[FullResultWrapper]:
        if self.testbed_config is None:
            raise ValueError("No testbed config is defined")
        
        if self.experiment_tag is None:
            raise ValueError("No experiment tag is defined")
        
        self.provider.set_testbed_config(self.testbed_config)
        full_result_wrapper = FullResultWrapper(self.testbed_config)
        self.provider.set_full_result_wrapper(full_result_wrapper)
        
        self.provider.update_experiment_tag(self.experiment_tag, True)

        from controller import Controller
        controller = Controller(self.provider)
        controller.init_config(parameters, testbed_package_path)

        status = controller.main()
        full_result_wrapper.controller_failed = not status
        full_result_wrapper.experiment_tag = self.provider.experiment

        controller.dismanlte()

        self.provider.release_experiment_tag()

        return FullResultWrapper

    def list_testbeds(self, from_all_users: bool = False) -> List[StateFileEntry]:
        from helper.state_file_helper import StateFileReader
        
        statefile_reader = StateFileReader(self.provider)
        return statefile_reader.get_states(filter_owned_by_executor=(not from_all_users))

    def export_results(self, additional_applications_path: Optional[str]) -> List[APISeriesContainer]:
        if self.testbed_config is None:
            raise ValueError("No testbed config defined")
        
        if self.experiment_tag is None:
            raise ValueError("No experiment tag is defined, random generation not possible for export")

        from helper.export_helper import ResultExportHelper
        self.provider.update_experiment_tag(self.experiment_tag, False)
        self.provider.set_testbed_config(self.testbed_config)

        exporter = ResultExportHelper(self.testbed_config, additional_applications_path, self.provider)
        return exporter.output_to_list()

    def clean_results(self, all: bool = False) -> None:
        if not all and self.experiment_tag is None:
            raise ValueError("No experiment tag is defined, random generation not possible for non-all clean")
        
        self.provider.update_experiment_tag(self.experiment_tag, False)
        
        from utils.influxdb import InfluxDBAdapter
        adapter = InfluxDBAdapter(self.provider)
        client = adapter.get_access_client()

        if client is None:
            raise Exception("Unable to create InfluxDB client")
        
        try:
            if not all:
                client.delete_series(tags={"experiment": self.provider.experiment})
            else:
                for measurement in client.get_list_measurements():
                    name = measurement["name"]
                    client.drop_measurement(name)
        except Exception as ex:
            raise ex
        finally:
            adapter.close_access_client()
