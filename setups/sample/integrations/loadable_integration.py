import time
import sys

from typing import Dict, Optional, Tuple
from dataclasses import dataclass

from utils.settings import IntegrationSettings
from base_integration import BaseIntegration, IntegrationStatusContainer


@dataclass
class LoadaleIntegrationSettings(IntegrationSettings):
    delay: int
    message: str


class AwaitIntegration(BaseIntegration):
    NAME = "loadable"

    def __init__(self, name: str, status_container: IntegrationStatusContainer, 
                 environment: Optional[Dict[str, str]] = None) -> None:
        super().__init__(name, status_container, environment)

    def set_and_validate_config(self, config: IntegrationSettings) -> Tuple[bool, Optional[str]]:
        try:
            self.settings = LoadaleIntegrationSettings(**config)
            return True, None
        except Exception as ex:
            return False, f"Config validation failed: {ex}"

    def is_integration_blocking(self) -> bool:
        return False
    
    def get_expected_timeout(self, at_shutdown: bool = False) -> int:
        if at_shutdown:
            return 0
        else:
            return self.settings.delay + 1

    def start(self) -> bool:
        time.sleep(self.settings.delay)
        print(self.settings.message, file=sys.stderr, flush=True)
        return True

    def stop(self) -> bool:
        return True
