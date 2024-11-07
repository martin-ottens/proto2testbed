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
from utils.settings import SettingsWrapper

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
    API_VERSION = "1.0"
    NAME = "##DONT_LOAD##"

    def __init__(self, name: str, status_container: IntegrationStatusContainer, 
                 environment: Optional[Dict[str, str]] = None) -> None:
        self.name = name
        self.environment = environment
        self.status = status_container
        self.base_path = Path(SettingsWrapper.cli_paramaters.config)
        self.settings = None

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

    def get_and_check_script(self, rel_path_str: str) -> Optional[Path]:
        script_file = self.base_path / Path(rel_path_str)
        if not script_file.exists() or not script_file.is_relative_to(self.base_path):
            logger.critical(f"Integration: Unable to find script file '{script_file}'!")
            return None

        if not bool(script_file.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)):
            logger.critical(f"Integration: Script file '{script_file}' has invalid permissions!")
            return None

        return script_file

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

    @abstractmethod
    def set_and_validate_config(self, config: IntegrationSettings) -> Tuple[bool, Optional[str]]:
        pass

    @abstractmethod
    def is_integration_blocking(self) -> bool:
        pass

    @abstractmethod
    def get_expected_timeout(self, at_shutdown: bool = False) -> int:
        pass

    # Needs to be implemeted blocking!
    @abstractmethod
    def start(self) -> bool:
        pass

    # Needs to be implemeted blocking!
    @abstractmethod
    def stop(self) -> bool:
        pass

