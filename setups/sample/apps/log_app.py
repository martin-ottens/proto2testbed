#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2024 Martin Ottens
# 
# This program is free software: you can redistribute it and/or modify 
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful, 
# but WITHOUT ANY WARRANTY; without even the implied warranty of 
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the 
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License 
# along with this program. If not, see https://www.gnu.org/licenses/.
#

import time

from typing import List, Tuple, Optional

from applications.base_application import BaseApplication
from applications.generic_application_interface import LogMessageLevel
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
    
    def exports_data(self) -> bool:
        return False
