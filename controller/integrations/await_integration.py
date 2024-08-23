import time

from typing import Dict, Optional
from pathlib import Path
from multiprocessing import Process

from utils.settings import IntegrationSettings, AwaitIntegrationSettings
from integrations.base_integration import BaseIntegration, IntegrationStatusContainer

class AwaitIntegration(BaseIntegration):
    def __init__(self, name: str, settings: IntegrationSettings, status_container: IntegrationStatusContainer, environment: Optional[Dict[str, str]] = None) -> None:
        super().__init__(name, settings, status_container, environment)
        if not isinstance(settings, AwaitIntegrationSettings):
            raise Exception("Received invalid settings type!")
        
        self.settings: AwaitIntegrationSettings = settings
        self.start_script: Path = self.__get_and_check_script(settings.start_script)
        self.process = None

    def is_integration_ready(self) -> bool:
        return self.start_script is not None

    def is_integration_blocking(self) -> bool:
        return False
    
    def get_expected_timeout(self, at_shutdown: bool = False) -> int:
        if at_shutdown:
            return 0
        else:
            return self.settings.start_delay + self.settings.wait_for_exit

    def start(self) -> bool:
        if self.settings.start_delay is not None and self.settings.start_delay > 0:
            time.sleep(self.settings.start_delay)

        self.process = Process(target=self.__run_subprocess, args=(self.start_script, ))
        self.process.start()
        self.process.join(timeout=self.settings.wait_for_exit)

        if self.process.is_alive():
            self.status.set_error("Integration timed out.")
            self.process.kill()
            self.process = None
            return False
        
        self.process = None
        return True

    def stop(self) -> bool:
        # WaitIntegration#stop is always async, so stop is only called after
        # successfull start, timeout or at forceful shutdown. Possible race
        # conditions here, but any errors due to that can be ignored. 
        try:
            if self.process is not None and self.process.is_alive():
                self.process.kill()
            return True
        except Exception:
            return False
