#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2024-2025 Martin Ottens
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

from typing import Dict, Optional, Tuple
from pathlib import Path
from multiprocessing import Process
from dataclasses import dataclass

from utils.settings import IntegrationSettings
from base_integration import BaseIntegration, IntegrationStatusContainer


@dataclass
class AwaitIntegrationSettings(IntegrationSettings):
    start_script: str
    wait_for_exit: int
    start_delay: int = 0


class AwaitIntegration(BaseIntegration):
    NAME = "await"

    def __init__(self, name: str, status_container: IntegrationStatusContainer, 
                 environment: Optional[Dict[str, str]] = None) -> None:
        super().__init__(name, status_container, environment)
        self.process = None
        self.settings = None
        self.start_script = None

    def set_and_validate_config(self, config: IntegrationSettings) -> Tuple[bool, Optional[str]]:
        try:
            self.settings = AwaitIntegrationSettings(**config)
            self.start_script: Path = self.get_and_check_script(self.settings.start_script)
            if self.start_script is None:
                return False, f"Unable to validate start script {self.settings.start_script}"
            else:
                return True, None
        except Exception as ex:
            return False, f"Config validation failed: {ex}"

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

        self.process = Process(target=self.run_subprocess, args=(self.start_script, ))
        self.process.start()
        self.process.join(timeout=self.settings.wait_for_exit)

        if self.process.is_alive():
            self.status.set_error("Integration timed out.")
            self.kill_process_with_child(self.process)
            self.process = None
            return False
        
        self.process = None
        return True

    def stop(self) -> bool:
        # WaitIntegration#stop is always async, so stop is only called after
        # successfully start, timeout or at forceful shutdown. Possible race
        # conditions here, but any errors due to that can be ignored. 
        try:
            if self.process is not None and self.process.is_alive():
                self.kill_process_with_child(self.process)
            return True
        except Exception:
            return False
