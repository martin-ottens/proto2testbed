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
from utils.state_provider import TestbedStateProvider


@dataclass
class StartStopIntegrationSettings(IntegrationSettings):
    start_script: str
    stop_script: str
    wait_for_exit: int = 5
    start_delay: int = -1


class StartStopIntegration(BaseIntegration):
    NAME = "startstop"

    def __init__(self, name: str, status_container: IntegrationStatusContainer, 
                 provider: TestbedStateProvider, environment: Optional[Dict[str, str]] = None) -> None:
        super().__init__(name, status_container, provider, environment)
        self.start_process = None
        self.settings = None
        self.start_script = None
        self.stop_script = None

    def set_and_validate_config(self, config: IntegrationSettings) -> Tuple[bool, Optional[str]]:
        try:
            self.settings = StartStopIntegrationSettings(**config)
            self.start_script: Path = self.get_and_check_script(self.settings.start_script)
            self.stop_script: Path = self.get_and_check_script(self.settings.stop_script)

            if self.start_script is None:
                return False, f"Unable to validate start script '{self.settings.start_script}'"

            if self.stop_script is None:
                return False, f"Unable to validate stop script '{self.settings.stop_script}'"

            return True, None
        except Exception as ex:
            return False, f"Config validation failed: {ex}"

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

        self.start_process = Process(target=self.run_subprocess, args=(self.start_script, ))
        self.start_process.start()
        self.start_process.join(timeout=self.settings.wait_for_exit)

        if self.start_process.is_alive():
            self.status.set_error("Integration timed out.")
            self.kill_process_with_child(self.start_process)
            self.start_process = None
            return False
        
        self.start_process = None
        return True

    def stop(self) -> bool:
        # Try to kill previously running start processes
        status = True
        try:
            if self.start_process is not None and self.start_process.is_alive():
                self.kill_process_with_child(self.start_process)
        except Exception:
            status = False

        # Execute stop script
        stop_process = Process(target=self.run_subprocess, args=(self.stop_script, ))
        stop_process.start()
        stop_process.join(timeout=self.settings.wait_for_exit)

        if stop_process.is_alive():
            self.status.set_error("Integration timed out.")
            self.kill_process_with_child(stop_process)
            return False
            
        return status
