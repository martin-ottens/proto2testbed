import time

from typing import List, Tuple, Optional

from base_application import BaseApplication
from application_interface import LogMessageLevel
from common.application_configs import ApplicationSettings

class LogApplicationConfig(ApplicationSettings):
    def __init__(self, messages: List[str], interval: int = 1, level: str = "INFO")  -> None:
        self.messages = messages
        self.interval = interval
        self.level = level

class LogApplication(BaseApplication):
    NAME = "log"

    def set_and_validate_config(self, config: ApplicationSettings) -> Tuple[bool, Optional[str]]:
        try:
            self.settings = LogApplicationConfig(**config)

            self.level_obj = LogMessageLevel.from_str(self.settings.level)

            if self.level_obj is None:
                return False, f"Unable to find log level {self.settings.level}"

            return True, None
        except Exception as ex:
            return False, f"Config validation failed: {ex}"
        
    def get_runtime_upper_bound(self, runtime: int) -> int:
        if self.settings is None:
            raise Exception("Can't calculate a runtime without settings.")

        return self.settings.interval * (1 + len(self.settings.messages))
        
    def start(self, runtime: int) -> bool:
        for message in self.settings.messages:
            self.interface.log(self.level_obj, message)
            time.sleep(self.settings.interval)

        return True