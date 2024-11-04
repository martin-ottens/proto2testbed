import os
import subprocess

from typing import Optional, Dict, Tuple

from base_application import BaseApplication
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
            os.chmod(self.settings.command.split(" ")[0], 0o777)
        except Exception:
            pass
        
        try:
            process = subprocess.Popen(self.settings.command, shell=True, 
                                       stdout=subprocess.PIPE, 
                                       stderr=subprocess.PIPE)
        except Exception as ex:
            raise Exception(f"Unable to run program '{self.settings.command}': {ex}")
        
        try:
            status = process.wait(runtime)
            if status != 0:
                raise Exception(f"Program '{self.settings.command}' exited with code {status}.\nSTDOUT: {process.stdout.readline().decode('utf-8')}\nSTDERR: {process.stderr.readline().decode('utf-8')}")
            
            return True
        except subprocess.TimeoutExpired as ex:
            process.kill()

            if self.settings.ignore_timeout:
                return True
            else:
                raise Exception(f"{ex}")
