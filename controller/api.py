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

import atexit
import copy

from typing import Optional, List
from pathlib import Path

from utils.settings import TestbedConfig
from full_result_wrapper import FullResultWrapper
from utils.state_provider import TestbedStateProvider
from helper.export_helper import APISeriesContainer
from helper.state_file_helper import StateFileEntry
from cli import CLI
from controller import Controller

class TestbedInitializationException(Exception):
    pass


class TestbedExecutionException(Exception):
    pass


class Proto2TestbedAPI:
    """
    Proto²Testbed API wrapper class. Allows to use Proto²Testbed from 
    Python programs instead of the CLI. Besides that, Proto²Testbed will
    use its default config (/etc/proto2testbed) and its libraries.
    Paths are relativ to the caller scripts location.
    """

    def __init__(self, 
                 verbose: int = 0, 
                 sudo: bool = False, 
                 disable_kvm: bool = False,
                 skip_integration: bool = False,
                 log_to_influx: bool = True) -> None:
        """
        Creates a new API instance with common settings applied to all 
        testbed executions.

        Args:
            verbose (int): Verbosity for internal logging. Default: 0
                           0 = info, 1 = debug (-v), 2 = trace (-vv)
            sudo (bool): Prepend sudo to all relevant commands. Default: False
            disable_kvm (bool): Disable the usage of KVM acceleration (e.g. 
                           when unavailable) Default: False (KVM is enabled)
            skip_integration (bool): Don't execute Integration on the host, even if
                           these are configured in the Testbed Config. If integrations
                           are disabled system-wide and Integrations are present in
                           the Testbed Config this value must be set to False, otherwise
                           the execution will fail. Default: False (Integrations will
                           be executed)
            log_to_influx (bool): Store results to InfluxDB instead of writing
                           them to FullResultWrapper object returned after 
                           testbed run. Default: True (Results are logged to InfluxDB)
        """

        if verbose not in [0, 1, 2]:
            raise ValueError("Inavlid verbose mode, select from 0, 1, 2.")

        CLI.setup_early_logging()
        self._provider = TestbedStateProvider(verbose=verbose,
                                             sudo=sudo,
                                             from_api_call=True,
                                             cache_datapoints=(not log_to_influx))

        self._disable_kvm = disable_kvm
        self._skip_integration = skip_integration
        
        self._cli = CLI(self._provider)
        self._stored_testbed_config: Optional[TestbedConfig] = None
        self._stored_controller: Optional[Controller] = None
        self._stored_result_wrapper: Optional[FullResultWrapper] = None
        atexit.register(self.destroy_testbed)

    def __del__(self) -> None:
        self.destroy_testbed()

    def load_testbed_config_from_package(self, 
                                         testbed_package_path: Path,
                                         skip_substitution: bool = True) -> TestbedConfig:
        """
        Load a testbed config from a JSON file and optionally resolve all 
        variables/substiutions using environment variables. In case variables
        needs to be replaced to create a valid JSON string and substution is not
        enabled, this method will fail.

        Args:
            testbed_package_path (Path): Path to the testbed package or 
                                        'testbed.json' file
            skip_substitution (bool): Toggle config variable substitutions with
                                      environment variables. Default: True (disabled)
        
        Returns:
            TestbedConfig: TestbedConfig object from the JSON file
        """
        from utils.config_tools import load_config
        from constants import TESTBED_CONFIG_JSON_FILENAME

        if not testbed_package_path.name.endswith(TESTBED_CONFIG_JSON_FILENAME):
            testbed_package_path = testbed_package_path / TESTBED_CONFIG_JSON_FILENAME

        return load_config(testbed_package_path, skip_substitution)
    

    def run_testbed(self, 
                    testbed_package_path: Path,
                    testbed_config: Optional[Path] = None,
                    experiment_tag: Optional[str] = None,
                    preserve_path: Optional[Path] = None,
                    use_checkpoints: bool = False,
                    overwrite_testbed: bool = False) -> FullResultWrapper:
        """
        Executes a testbed, blocks until the testbed execution is finsished.
        This method can be used in two different ways:
        - Single-Shot Operation:

          Testbed Creation --> App Installation --> Experiment --> Testbed Dismantling

          Single-Shot operation is used when use_checkpoint is False. This is useful 
          for single experiments, where the initial testbed setup is not used any 
          further. No checkpoints are created in this operation, which reduces
          execution time and memory consumption.

        - Checkpoint Operation:
                                  Checkpoint Restore
                                   |               |
                                   V               | 
          Testbed Creation --> Checkpoint     Dirty State --> Testbed Dismantling
                                   |               ^
                                   V               |
                           App Installation --> Experiment

           Checkpoint operation can be used when create_checkpoint is True. This
           operation is used when multiple experiments with minor config differences
           are using the same testbed setup (topology and setup scripts). Setup scripts
           must succeed for this operation mode. Between different runs, all Application
           Configs of the Instances in the Testbed Config can be changed (but not other 
           configs). The preserve_path and the experiment_tag can also be changed.

           A typical workflow would look like this:
           1. Run the testbed (run_testbed) with use_checkpoint=True
           2. Use the results in the FullResultWrapper
           3. Run the testbed again (run_testbed) with different Applications,
              experiment_tag or preserve_path. The checkpoint after the setup_script
              execution is loaded automatically.
           4. Goto 2, repeat until all experiments are finished
           5. Destory the testbed (destory_testbed)

           The Single-Shot operation can be reproduced by execution the steps 1, 5 and 2.
        
        Exceptions are raised on errors. When the Testbed initialization (toplogy, setup s
        cripts) failed, a TestbedInitializationException is raised. In this case, the 
        Checkpoint Operation cannot be continued.

        Args:
            testbed_package_path (str): Path to the testbed package root directory
                                        containing assets for the execution like scripts
                                        or additional Integrations and Applications
            testbed_config (TestbedConfig | None): Testbed Config object. If None, the
                                        method will try to load the config from within
                                        the testbed_package_path. Default: None (load from 
                                        testbed_package_path)
            experiment_tag (str | None): Experiment tag for testbed identification and data
                                        tagging when exported to the InfluxDB. Will be 
                                        generated automatically when None is used, the
                                        generated experiment tag can be obtained from the
                                        FullResultWrapper in this case. Default: None 
                                        (random generated)
            preserve_path (Path | None): Base path for file preservation, None to fully 
                                        disablefile preservation. Default: None (file 
                                        preservation disbaled)
            use_checkpoints (bool): Enable Checkpoint operation. Default: False (use 
                                        Singe-Shot operation)
            overwrite_testbed (bool): Allow to detroy and re-initialize the testbed when
                                      transitioning from Checkpoint to Single-Shot
                                      operation. Default: False (throw an Exception in
                                      case a testbed is already present)

        Returns:
            FullResultWrapper: Wrapper object with logs, application status reports,
                               instance status reports and data points (when 
                               log_to_influxdb is not enabled)
        """

        if testbed_config is None:
            testbed_config = self.load_testbed_config_from_package(testbed_package_path)

        if not use_checkpoints and self._stored_controller is not None:
            if not overwrite_testbed:
                raise ValueError("A testbed exisists with prepared checkpoint amd overwrite is disabled")
            else:
                self.destroy_testbed()

        if not self._provider.update_preserve_path(preserve_path):
            raise ValueError("Invalid preserve Path")
        
        if self._stored_controller is None:
            self._provider.set_testbed_config(testbed_config, testbed_package_path)
            self._stored_testbed_config = copy.deepcopy(testbed_config)
            self._stored_result_wrapper = FullResultWrapper(testbed_config, testbed_package_path)
            self._provider.set_full_result_wrapper(self._stored_result_wrapper)
            self._provider.update_experiment_tag(experiment_tag, True)

            self._stored_controller = Controller(self._provider, self._cli)

            try:
                self._stored_controller.init_config(skip_integration=self._skip_integration,
                                                    disable_kvm=self._disable_kvm,
                                                    create_checkpoint=use_checkpoints)
                init_state = self._stored_controller.initialize_testbed()
                if init_state.has_failed:
                    return copy.deepcopy(self._stored_result_wrapper)
            except Exception as ex:
                self.destroy_testbed()
                raise TestbedInitializationException("Testbed initialization failed") from ex
        else:
            self._provider.update_experiment_tag(experiment_tag, True)

            try:
                self._stored_controller.reset_testbed_to_snapshot()
            except Exception as ex:
                self.destroy_testbed()
                raise TestbedInitializationException("Testbed checkpoint restore failed") from ex

            try:
                self._stored_testbed_config.is_identical_besides_experiments(testbed_config)
                self._provider.set_testbed_config(testbed_config, testbed_package_path)
                self._stored_testbed_config = copy.deepcopy(testbed_config)
            except Exception as ex:
                raise ex
        
        try:
            run_state = self._stored_controller.execute_testbed()
            if not run_state.can_continue:
                raise TestbedExecutionException("Testbed execution failed with error that cannot be fixed by a snapshot restore.")
        
            self._stored_result_wrapper.controller_succeeded = not run_state.has_failed
        except Exception as ex:
            self._stored_controller.copy_presere_files()
            self.destroy_testbed()
            raise ex

        self._stored_controller.copy_presere_files()
        result_wrapper = copy.deepcopy(self._stored_result_wrapper)

        if not use_checkpoints:
            self.destroy_testbed()

        return result_wrapper
    
    def destroy_testbed(self) -> None:
        """
        Destroy the testbed after the Checkpoint operation is completed. This
        method is also called using an atexit hook.
        """
        if self._stored_controller is not None:
            try:
                self._stored_controller.dismantle()
            except Exception:
                pass

            self._provider.release_experiment_tag()
            self._provider.clear()
            self._stored_controller = None
        
        self._stored_testbed_config = None
        self._stored_result_wrapper = None

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

    def export_results(self, 
                       experiment_tag: str,
                       testbed_config: Optional[TestbedConfig] = None,
                       testbed_package_path: Optional[Path] = None) -> List[APISeriesContainer]:
        """
        Export data points from the InfluxDB, e.g., when not stored in the 
        FullResultWrapper. A Testbed Package path can be specified when 
        loadable application are refered in the Testbed Config. When no Testbed 
        Config is provided, it is tried to load it from the Testbed Package.

        Args:
            experiment_tag (str): Experiment tag for result export
            testbed_config (TestbedConfig | None): Optional Testbed Config
                                  object. If None, it will be loaded from the
                                  testbed_package_path if possible, default: None
            testbed_package_path (Path | None): Optional path for the Testbed Package.
                                  This will be used to load additional Applications
                                  (referend in the Testbed Config) or to load the 
                                  Testbed Config (when testbed_config is None),
                                  default: None
        
        Returns:
            List[APISeriesContainer]: All measurements obatined from the InfluxDB for 
                                      the testbed config and experiment tag. A single
                                      measurement is contained in an individual
                                      APISeriesConatiner
        """
        
        if testbed_config is None:
            if testbed_package_path is None:
                raise ValueError("No testbed config defined and no path provided to load.")
            
            testbed_config = self.load_testbed_config_from_package(testbed_package_path)
        
        if experiment_tag is None or experiment_tag == "":
            raise ValueError("No experiment tag is defined, random generation not possible for export")

        from helper.export_helper import ResultExportHelper
        self._provider.update_experiment_tag(experiment_tag, False)
        self._provider.set_testbed_config(testbed_config, testbed_package_path)

        exporter = ResultExportHelper(testbed_config, 
                                      testbed_package_path, 
                                      self._provider)
        return exporter.output_to_list()
    
    def export_results_from_wrapper(self, result_wrapper: FullResultWrapper) -> List[APISeriesContainer]:
        """
        Export data points from the InfluxDB, e.g., when not stored in the 
        FullResultWrapper. Uses the testbed config, testbed package path, and
        the experiment tag stored in a FullResultWrapper object obtained from a testbed
        execution.

        Args:
            result_wrapper (FullResultWrapper): FullResultWrapper obtained from a testbed execution,
                                                used to obtain the experiment tag used/generated during
                                                the testbed execution, the testbed config used and
                                                the testbed package path.
        
        Returns:
            List[APISeriesContainer]: All measurements obatined from the InfluxDB for 
                                      the testbed config and experiment tag. A single
                                      measurement is contained in an individual
        """

        if result_wrapper.testbed_config is None or result_wrapper.testbed_package_path is None:
            raise ValueError("FullResultWrapper is in invalid state: No testbed config provided.")
        
        if result_wrapper.experiment_tag is None:
            raise ValueError("FullResultWrapper is in invalid state: No experiment tag provided.")
        
        return self.export_results(experiment_tag=result_wrapper.experiment_tag,
                                   testbed_config=result_wrapper.testbed_config,
                                   testbed_package_path=result_wrapper.testbed_package_path)

    def clean_results(self, 
                      experiment_tag: Optional[str] = None,
                      all: bool = False) -> None:
        """
        Delete results from the InfluxDB. All results can be deleted or just the 
        results for the experiment tag currently set in the API wrapper instance.

        Args:
            experiment_tag (str | None): Experiment tag for delete entries from
                                         InfluxDB. Must be set when all is set to
                                         False, default: None
            all (bool): Delete ALL results from the InfluxDB, default: False
        """
        if not all and (experiment_tag is None or experiment_tag == ""):
            raise ValueError("No experiment tag is defined, random generation not possible for non-all clean")
        
        self._provider.update_experiment_tag(experiment_tag, False)
        
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

    def clean_results_from_wrapper(self, result_wrapper: FullResultWrapper) -> List[APISeriesContainer]:
        """
        Delete results from the InfluxDB as referenced by the experiment tag in the FullResultWrapper

        Args:
            result_wrapper (FullResultWrapper): FullResultWrapper obtained from a testbed execution,
                                                used to obtain the experiment tag used/generated during
                                                the testbed execution.
        """

        if result_wrapper.experiment_tag is None:
            raise ValueError("FullResultWrapper is in invalid state: No experiment tag provided.")
        
        return self.clean_results(experiment_tag=result_wrapper.experiment_tag, all=False)
