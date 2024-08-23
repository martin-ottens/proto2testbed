from typing import Dict, Optional
from pathlib import Path

from utils.settings import IntegrationSettings, AwaitIntegrationSettings
from integrations.base_integration import BaseIntegration, IntegrationStatusContainer

class AwaitIntegration(BaseIntegration):
    def __init__(self, name, str, settings: IntegrationSettings, status_container: IntegrationStatusContainer, environment: Optional[Dict[str, str]] = None) -> None:
        super().__init__(name, settings, status_container, environment)
        if not isinstance(settings, AwaitIntegrationSettings):
            raise Exception("Received invalid settings type!")
        
        self.settings: AwaitIntegrationSettings = settings
        self.start_script: Path = self.__get_and_check_script(settings.start_script)

    def is_integration_ready(self) -> bool:
        return self.start_script is not None

    def is_integration_blocking(self) -> bool:
        return False

    def start(self) -> bool:
        pass

    def stop(self) -> bool:
        pass
