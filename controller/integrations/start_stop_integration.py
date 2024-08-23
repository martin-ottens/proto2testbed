import time

from typing import Dict, Optional
from pathlib import Path
from multiprocessing import Process

from utils.settings import IntegrationSettings, StartStopIntegrationSettings
from integrations.base_integration import BaseIntegration, IntegrationStatusContainer

class StartStopIntegration(BaseIntegration):
    def __init__(self, name: str, settings: IntegrationSettings, status_container: IntegrationStatusContainer, environment: Optional[Dict[str, str]] = None) -> None:
        super().__init__(name, settings, status_container, environment)
        if not isinstance(settings, StartStopIntegrationSettings):
            raise Exception("Received invalid settings type!")
        
        self.settings: StartStopIntegrationSettings = settings
        self.start_script: Path = self.__get_and_check_script(settings.start_script)
        self.stop_script: Path = self.__get_and_check_script(settings.stop_script)
        self.start_process = None

    def is_integration_ready(self) -> bool:
        if self.start_script is None or self.stop_script is None:
            return False

    def is_integration_blocking(self) -> bool:
        return self.settings.start_delay == -1

    def get_expected_timeout(self, at_shutdown: bool = False) -> int:
        if at_shutdown:
            return self.settings.wait_for_exit
        else:
            return self.settings.start_delay + self.settings.wait_for_exit

    def start(self) -> bool:
        if self.settings.start_delay is not None and self.settings.start_delay > 0:
            time.sleep(self.settings.start_delay)

        self.start_process = Process(target=self.__run_subprocess, args=(self.start_script, ))
        self.start_process.start()
        self.start_process.join(timeout=self.settings.wait_for_exit)

        if self.start_process.is_alive():
            self.status.set_error("Integration timed out.")
            self.start_process.kill()
            self.start_process = None
            return False
        
        self.start_process = None
        return True

    def stop(self) -> bool:
        # Try to kill previously running start processes
        status = True
        try:
            if self.start_process is not None and self.start_process.is_alive():
                self.start_process.kill()
        except Exception:
            status = False

        # Execute stop script
        stop_process = Process(target=self.__run_subprocess, args=(self.stop_script, ))
        stop_process.start()
        stop_process.join(timeout=self.settings.wait_for_exit)

        if stop_process.is_alive():
            self.status.set_error("Integration timed out.")
            stop_process.kill()
            return False
            
        return status
