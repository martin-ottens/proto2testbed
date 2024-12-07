import os
import subprocess

from pathlib import Path
from typing import Optional, Dict, Tuple

from applications.base_application import BaseApplication
from common.application_configs import ApplicationSettings


class RunProgramApplicationConfig(ApplicationSettings):
    def __init__(self, command: str, ignore_timeout: bool = False, 
                 environment: Optional[Dict[str, str]] = None) -> None:
        self.command = command
        self.ignore_timeout = ignore_timeout
        self.environment = environment


class RunProgramApplication(BaseApplication):
    NAME = "run-program"

    def set_and_validate_config(self, config: ApplicationSettings) -> Tuple[bool, Optional[str]]:
        try:
            self.settings = RunProgramApplicationConfig(**config)

            parts = self.settings.command.split(" ", maxsplit=1)
            self.relative_command = Path(parts[0])
            self.command = Path(parts[0])
            self.args = parts[1] if len(parts) >= 2 else ""

            self.from_tbp = False
            if not self.command.is_absolute():
                from global_state import GlobalState
                
                self.command = GlobalState.testbed_package_path / self.command
                self.from_tbp = True

            if not self.command.exists():
                if self.from_tbp:
                    return False, f"Unable to find file: 'TESTBED-PACKAGE/{self.relative_command}'"
                else:
                    return False, f"Unable to find file: '{self.command}'"

            if not os.access(self.command, os.X_OK):
                if self.from_tbp:
                    return False, f"File 'TESTBED-PACKAGE/{self.relative_command}' is not executable."
                else:
                    try:
                        os.chmod(self.command, 0o777)
                    except Exception as ex:
                        return False, f"Unable to make '{self.command}' executable: {ex}"

            return True, None
        except Exception as ex:
            return False, f"Config validation failed: {ex}"

    def start(self, runtime: int) -> bool:
        if self.settings is None:
            return False

        if self.settings.environment is not None:
            for k, v in self.settings.environment.items():
                os.environ[k] = str(v)
        
        try:
            process = subprocess.Popen(f"{self.command} {self.args}", shell=True, 
                                       stdout=subprocess.PIPE, 
                                       stderr=subprocess.PIPE)
        except Exception as ex:
            if self.from_tbp:
                raise Exception(f"Unable to run program 'TESTBED-PACKAGE/{self.relative_command}': {ex}")
            else:
                raise Exception(f"Unable to run program '{self.command}': {ex}")
        try:
            status = process.wait(runtime)
            if status != 0:
                if self.from_tbp:
                    raise Exception(f"Program 'TESTBED-PACKAGE/{self.relative_command}' exited with code {status}.\nSTDOUT: {process.stdout.readline().decode('utf-8')}\nSTDERR: {process.stderr.readline().decode('utf-8')}")
                else:
                    raise Exception(f"Program '{self.command}' exited with code {status}.\nSTDOUT: {process.stdout.readline().decode('utf-8')}\nSTDERR: {process.stderr.readline().decode('utf-8')}")
            
            return True
        except subprocess.TimeoutExpired as ex:
            process.kill()

            if self.settings.ignore_timeout:
                return True
            else:
                raise Exception(f"Timeout during program execution: {ex}")
