import os
import subprocess

from base_application import BaseApplication
from common.application_configs import ApplicationConfig, RunProgramApplicationConfig
from application_interface import ApplicationInterface


class RunProgramApplication(BaseApplication):
    def set_and_validate_config(self, config: ApplicationConfig) -> bool:
        pass

    def start_collection(self, runtime: int) -> bool:
        if not isinstance(settings, RunProgramApplicationConfig):
            raise Exception("Received invalid config type!")
        
        if settings.environment is not None:
            for k, v in settings.environment.items():
                os.environ[k] = str(v)

        try:
            os.chmod(settings.command.split(" ")[0], 0o777)
        except Exception:
            pass
        
        try:
            process = subprocess.Popen(settings.command, shell=True, 
                                       stdout=subprocess.PIPE, 
                                       stderr=subprocess.PIPE)
        except Exception as ex:
            raise Exception(f"Unable to run program '{settings.command}': {ex}")
        
        try:
            status = process.wait(runtime)
            if status != 0:
                raise Exception(f"Program '{settings.command}' exited with code {status}.\nSTDOUT: {process.stdout.readline().decode('utf-8')}\nSTDERR: {process.stderr.readline().decode('utf-8')}")
            
            return True
        except subprocess.TimeoutExpired as ex:
            process.kill()

            if settings.ignore_timeout:
                return True
            else:
                raise Exception(f"{ex}")
