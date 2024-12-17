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
import stat
import psutil
import signal
import threading

from pathlib import Path
from abc import ABC, abstractmethod
from typing import Optional, Dict, Tuple
from loguru import logger
from multiprocessing import Process, Manager

from utils.settings import IntegrationSettings
from utils.system_commands import invoke_subprocess
from utils.settings import TestbedSettingsWrapper

class IntegrationStatusContainer():
    def __init__(self) -> None:

        # Manager used for ICP (subprocesses)
        self._manager = Manager()
        self._shared_state = self._manager.dict()
        self._shared_state["error_flag"] = False
        self._shared_state["error_string"] = None

        # Flag used only by Wrapper thread -> pseudo-parallel
        self._flag = threading.Event()
        self._flag.clear()
    
    def reset_error(self):
        self._shared_state["error_flag"] = False
        self._shared_state["error_string"] = None

    def reset(self):
        self.reset_error()
        self._flag.clear()
    
    def set_error(self, error_string: str) -> None:
        self._shared_state["error_flag"] = True
        self._shared_state["error_string"] = error_string

    def get_error(self) -> Optional[str]:
        if self._shared_state["error_flag"] is not True:
            return None
        else:
            return self._shared_state["error_string"]
    
    def set_finished(self):
        self._flag.set()

    def get_finished_flag(self) -> threading.Event:
        return self._flag


class BaseIntegration(ABC):
    # API version of the Integration, currently only 1.0 is used (optional)
    API_VERSION = "1.0"

    # Name of the Integration. Used to referenced bundeled Integrations and for logging.
    NAME = "##DONT_LOAD##"

    # Constructor, the "name" and "environment" is passed from the corresponding Integration
    # settings from the Testbed Configuration. The "status_container" is used to allow
    # subprocesses to communicate with the Testbed Controller. Subclasses should call the
    # BaeeIntegration's constructor using super.
    def __init__(self, name: str, status_container: IntegrationStatusContainer, 
                 environment: Optional[Dict[str, str]] = None) -> None:
        self.name = name
        self.environment = environment
        self.status = status_container
        self.base_path = Path(TestbedSettingsWrapper.cli_paramaters.config)
        self.settings = None

    # Helper function to kill a process with all of its child. Do not overwrite.
    def kill_process_with_child(self, process: Process):
        try:
            parent = psutil.Process(process.ident)
            for child in parent.children(recursive=True):
                try: child.send_signal(signal.SIGTERM)
                except Exception as ex:
                    logger.opt(exception=ex).critical("Integration: Unable to kill child.")
                    continue
        except Exception as ex:
            logger.opt(exception=ex).critical("Integration: Unable to get child processes.")

        process.terminate()

    # Helper function to check a script that is, for example, executed by the Integration.
    # Do not overwrite.
    def get_and_check_script(self, rel_path_str: str) -> Optional[Path]:
        script_file = self.base_path / Path(rel_path_str)
        if not script_file.exists() or not script_file.is_relative_to(self.base_path):
            logger.critical(f"Integration: Unable to find script file '{script_file}'!")
            return None

        if not bool(script_file.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)):
            logger.critical(f"Integration: Script file '{script_file}' has invalid permissions!")
            return None

        return script_file

    # Helper function to run a script inside a new subprocess while monitoring its status.
    # Do not overwrite.
    def run_subprocess(self, script_path: Path, shell: bool = False, precommand: Optional[str] = "/bin/bash"):
        """
        Important: This method will be forked away from the main process!
        """

        if self.environment is not None:
            for k, v in self.environment.items():
                os.environ[k] = str(v)
        
        try:
            if precommand is None:
                cmd = str(script_path)
            else:
                cmd = [precommand, str(script_path)]

            proc = invoke_subprocess(cmd, capture_output=True, shell=shell)
            stderr = proc.stderr.decode("utf-8")
            if proc is not None and (proc.returncode != 0 or stderr != ""):
                if stderr != "":
                    self.status.set_error(f"Failed with exit code {proc.returncode}\nSTDOUT: {proc.stdout.decode('utf-8')}\nSTDERR: {stderr}")
                else:
                    self.status.set_error(f"Failed with exit code {proc.returncode}\nSTDOUT: {proc.stdout.decode('utf-8')}")
        except Exception as ex:
            self.status.set_error(f"Error during execution: {ex}")

    # The config from the Integration-specific part of the Integration config from the Testbed Package
    # is passed to this method. This method needs to validate this config and store it for later use 
    # (e.g., in the start or stop method). It returns, wether the validation was successful, optionally, an 
    # error message can be added, that is logged (use "None" for no message) 
    @abstractmethod
    def set_and_validate_config(self, config: IntegrationSettings) -> Tuple[bool, Optional[str]]:
        pass

    # Returns, if the start and stop methods are blocking: If blocking is enabled, the testbed waits 
    # until the start and stop methods return before proceeding. Otherwise, the testbed just waits 
    # for the configured "wait_after_invoke" time before proceeding. This method is called, after the
    # config has been set.
    @abstractmethod
    def is_integration_blocking(self) -> bool:
        pass
    
    # Returns the expected timeout in seconds for the start method (if "at_shutdown" is False) or 
    # for the stop method (if "at_shutdown" is True). When the returned timeout is exceeded, the 
    # Controller will consider the Integration as failed. This method is called, after the
    # config has been set.
    @abstractmethod
    def get_expected_timeout(self, at_shutdown: bool = False) -> int:
        pass

    # Start the Integration, this needs to be implemeted blocking, regardless if 
    # "is_integration_blocking" returns True. The return value is the status of the
    # start stage of the Integration.
    @abstractmethod
    def start(self) -> bool:
        pass

    # Stop the Integration, this needs to be implemeted blocking, regardless if 
    # "is_integration_blocking" returns True. The return value is the status of the
    # stop stage of the Integration. Note that stop is called under all cirumstances,
    # especially, when start reports a failure. This method should reset the state of
    # the Testbed Host.
    @abstractmethod
    def stop(self) -> bool:
        pass
