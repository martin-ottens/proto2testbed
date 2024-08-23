from typing import Dict, Optional
from pathlib import Path

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

    def is_integration_ready(self) -> bool:
        if self.start_script is None or self.stop_script is None:
            return False

    def is_integration_blocking(self) -> bool:
        # Blocks, when no delay (= -1) is given
        return self.start_script == -1

    def start(self) -> bool:
        pass

    def stop(self) -> bool:
        pass
