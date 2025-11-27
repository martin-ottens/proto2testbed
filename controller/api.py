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
from pathlib import Path

from utils.settings import TestbedConfig, RunParameters
from full_result_wrapper import FullResultWrapper
from utils.state_provider import TestbedStateProvider
from helper.export_helper import APISeriesContainer
from helper.state_file_helper import StateFileEntry
from cli import CLI

class Proto2TestbedAPI:
    """
    Proto²Testbed API wrapper class. Allows to use Proto²Testbed from 
    Python programs instead of the CLI. Besides that, Proto²Testbed will
    use its default config (/etc/proto2testbed) and its libraries.
    Paths are relativ to the caller scripts location.
    """

    def __init__(self, verbose: int = 0, sudo: bool = False, 
                 log_to_influx: bool = True) -> None:
        """
        Creates a new API instance.

        Args:
            verbose (int): Verbosity for internal logging, default: 0
                           0 = info, 1 = debug (-v), 2 = trace (-vv)
            sudo (bool): Prepend sudo to all relevant commands, default: False
            log_to_influx (bool): Store results to InfluxDB instead of writing
                                  them to FullResultWrapper object returned
                                  after testbed run, default: True
        """

        if verbose not in [0, 1, 2]:
            raise ValueError("Inavlid verbose mode, select from 0, 1, 2.")

        CLI.setup_early_logging()

        self._testbed_config: Optional[TestbedConfig] = None
        self._experiment_tag: Optional[str] = None
        self._provider = TestbedStateProvider(verbose=verbose,
                                             sudo=sudo,
                                             from_api_call=True,
                                             cache_datapoints=(not log_to_influx))
        
        self._cli = CLI(self._provider)

    def set_testbed_config(self, config: TestbedConfig) -> None:
        """
        Update the testbed config used by other methods. A testbed config must
        be set before a testbed run can be started.

        Args:
            config (TestbedConfig): TestbedConfig object that should not
                                    contain any unresolved varaibles/subsitutions
        """
        self._testbed_config = config

    def set_experiment_tag(self, tag: Optional[str]) -> None:
        """
        Update the experiment tag used by other methods.

        Args:
            tag (str | None): The experiment tag, None to randomly generate
                              an experiment tag for testbed run
        """
        self._experiment_tag = tag

    def load_testbed_config_from_package(self, testbed_package_path: str, 
                                      skip_substitution: bool = True) -> TestbedConfig:
        """
        Load a testbed config from a JSON file and optionally resolve all 
        variables/substiutions using environment variables. In case variables
        needs to be replaced to create a valid JSON string and substution is not
        enabled, this method will fail.

        Args:
            testbed_package_path (str): Path to the testbed package or 
                                        'testbed.json' file
            skip_substitution (bool): Toggle config variable substitutions with
                                      environment variables, default: True (disabled)
        
        Returns:
            TestbedConfig: TestbedConfig object from the JSON file
        """
        from utils.config_tools import load_config
        from constants import TESTBED_CONFIG_JSON_FILENAME
        from pathlib import Path

        if not testbed_package_path.endswith(TESTBED_CONFIG_JSON_FILENAME):
            testbed_package_path = f"{testbed_package_path}/{TESTBED_CONFIG_JSON_FILENAME}"

        return load_config(Path(testbed_package_path), skip_substitution)

    def run_testbed(self, testbed_package_path: str, 
                    parameters: Optional[RunParameters] = None,
                    preseve_path: Optional[Path] = None) -> FullResultWrapper:
        """
        Executes a testbed, blocks until the testbed execution is finsished.
        A testbed config object needs to be provided before calling this method.
        Additional RunParameters can be used to configure different run-specific
        testbed settings (e.g., file preservation).

        Args:
            testbed_package_path (str): Path to the testbed package root directory
                                        containing assets for the execution like scripts
            parameters (RunParameters | None): Additional testbed execution settings,
                                               defaults to None, in this case the testbed will 
                                               use default settings
            preserve_path (Path | None): Base path for file preservation, None to fully disable
                                         file preservation

        Returns:
            FullResultWrapper: Wrapper object with logs, application status reports,
                               instance status reports and data points (when 
                               log_to_influxdb is not enabled)
        """

        if self._testbed_config is None:
            raise ValueError("No testbed config is defined")
        
        if parameters is None:
            parameters = RunParameters()
        
        self._provider.set_testbed_config(self._testbed_config)

        if not self._provider.update_preserve_path(preseve_path, Path(testbed_package_path)):
            raise Exception("Invalid preserve Path")
        
        full_result_wrapper = FullResultWrapper(self._testbed_config)
        self._provider.set_full_result_wrapper(full_result_wrapper)
        
        self._provider.update_experiment_tag(self._experiment_tag, True)

        from controller import Controller
        controller = Controller(self._provider, self._cli)
        controller.init_config(parameters)

        try:
            status = controller.main()
            full_result_wrapper.controller_succeeded = status
            full_result_wrapper.experiment_tag = self._provider.experiment
        except Exception as ex:
            raise ex
        finally:
            controller.dismantle()
            self._provider.release_experiment_tag()
            self._provider.clear()

        return full_result_wrapper

    def list_testbeds(self, from_all_users: bool = False) -> List[StateFileEntry]:
        """
        List the currently running testbeds on the system or by the current user.

        Args:
            from_all_users (bool): Return all system wide testbed runs and not just
                                   the testbeds executed by the current user, 
                                   default: False
        
        Returns:
            List[StateFileEntry]: List of all running testbeds matching the search
                                  criteria
        """
        from helper.state_file_helper import StateFileReader
        
        statefile_reader = StateFileReader(self._provider)
        return statefile_reader.get_states(filter_owned_by_executor=(not from_all_users))

    def export_results(self, additional_applications_path: Optional[str] = None) -> List[APISeriesContainer]:
        """
        Export data points from the InfluxDB. For this, the corresponding testbed
        config must be set and an experiment tag needs to be defined. A testbed 
        package path can be specified when loadable application are refered in the
        testbed config.

        Args:
            additional_applications_path (str | None): Path to a testbed package root
                                    in which the application loader can find python
                                    files containing loadable applications refered to
                                    in the testbed config
        
        Returns:
            List[APISeriesContainer]: All measurements obatined from the InfluxDB for 
                                      the testbed config and experiment tag. A single
                                      measurement is contained in an individual
                                      APISeriesConatiner
        """
        
        if self._testbed_config is None:
            raise ValueError("No testbed config defined")
        
        if self._experiment_tag is None:
            raise ValueError("No experiment tag is defined, random generation not possible for export")

        from helper.export_helper import ResultExportHelper
        self._provider.update_experiment_tag(self._experiment_tag, False)
        self._provider.set_testbed_config(self._testbed_config)

        exporter = ResultExportHelper(self._testbed_config, 
                                      additional_applications_path, 
                                      self._provider)
        return exporter.output_to_list()

    def clean_results(self, all: bool = False) -> None:
        """
        Delete results from the InfluxDB. All results can be deleted or just the 
        results for the experiment tag currently set in the API wrapper instance.

        Args:
            all (bool): Delete ALL results from the InfluxDB, default: False
        """
        if not all and self._experiment_tag is None:
            raise ValueError("No experiment tag is defined, random generation not possible for non-all clean")
        
        self._provider.update_experiment_tag(self._experiment_tag, False)
        
        from utils.influxdb import InfluxDBAdapter
        adapter = InfluxDBAdapter(self._provider)
        client = adapter.get_access_client()

        if client is None:
            raise Exception("Unable to create InfluxDB client")
        
        try:
            if not all:
                client.delete_series(tags={"experiment": self._provider.experiment})
            else:
                for measurement in client.get_list_measurements():
                    name = measurement["name"]
                    client.drop_measurement(name)
        except Exception as ex:
            raise ex
        finally:
            adapter.close_access_client()
