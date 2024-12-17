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

import os
import subprocess

from pathlib import Path
from typing import Optional, Dict, Tuple

from applications.base_application import BaseApplication
from common.application_configs import ApplicationSettings

"""
Run a command or script on the Instance. The command or script should be
given as a path, if the path is relative, it is interpreted relative to the
Testbed Package's root. 

The setting value "command" contains that path alongside with additional arguments.
It is possible to use expressions like '/bin/bash <script>'. The script or program
should be executable. "environment" contains a key-value-dictionary that is passed
as environment variables to the command or script. The script or command is 
always terminated when the "timeout" is exceeded, the "ignore_timeout" setting can
be used to define if that should be interpreted as a failure of this Application 
and defaults to "false". Settings "environment" and "ignore_timeout" are optional.

Example config:
    {
        "application": "run-program",
        "name": "run-my-script",
        "delay": 0,
        "runtime": 60,
        "settings": {
            "command": "my-instance/run-script.sh", // in this case: relative to Testbed Package
            "environment": {
                "KEY": "VALUE",
                "REPEAT": "10"
            }
            "ignore_timeout": true // Timeout is not treated as a failure
        }
    }
"""

class RunProgramApplicationConfig(ApplicationSettings):
    def __init__(self, command: str, ignore_timeout: bool = False, 
                 environment: Optional[Dict[str, str]] = None) -> None:
        self.command = command
        self.ignore_timeout = ignore_timeout
        self.environment = environment


class RunProgramApplication(BaseApplication):
    NAME = "run-program"

    def set_and_validate_config(self, config: ApplicationSettings) -> Tuple[bool, Optional[str]]:
        try:
            self.settings = RunProgramApplicationConfig(**config)

            parts = self.settings.command.split(" ", maxsplit=1)
            self.relative_command = Path(parts[0])
            self.command = Path(parts[0])
            self.args = parts[1] if len(parts) >= 2 else ""

            self.from_tbp = False
            if not self.command.is_absolute():
                from global_state import GlobalState
                
                self.command = GlobalState.testbed_package_path / self.command
                self.from_tbp = True

            if not self.command.exists():
                if self.from_tbp:
                    return False, f"Unable to find file: 'TESTBED-PACKAGE/{self.relative_command}'"
                else:
                    return False, f"Unable to find file: '{self.command}'"

            if not os.access(self.command, os.X_OK):
                if self.from_tbp:
                    return False, f"File 'TESTBED-PACKAGE/{self.relative_command}' is not executable."
                else:
                    try:
                        os.chmod(self.command, 0o777)
                    except Exception as ex:
                        return False, f"Unable to make '{self.command}' executable: {ex}"

            return True, None
        except Exception as ex:
            return False, f"Config validation failed: {ex}"

    def start(self, runtime: int) -> bool:
        if self.settings is None:
            return False

        if self.settings.environment is not None:
            for k, v in self.settings.environment.items():
                os.environ[k] = str(v)
        
        try:
            process = subprocess.Popen(f"{self.command} {self.args}", shell=True, 
                                       stdout=subprocess.PIPE, 
                                       stderr=subprocess.PIPE)
        except Exception as ex:
            if self.from_tbp:
                raise Exception(f"Unable to run program 'TESTBED-PACKAGE/{self.relative_command}': {ex}")
            else:
                raise Exception(f"Unable to run program '{self.command}': {ex}")
        try:
            status = process.wait(runtime)
            if status != 0:
                if self.from_tbp:
                    raise Exception(f"Program 'TESTBED-PACKAGE/{self.relative_command}' exited with code {status}.\nSTDOUT: {process.stdout.readline().decode('utf-8')}\nSTDERR: {process.stderr.readline().decode('utf-8')}")
                else:
                    raise Exception(f"Program '{self.command}' exited with code {status}.\nSTDOUT: {process.stdout.readline().decode('utf-8')}\nSTDERR: {process.stderr.readline().decode('utf-8')}")
            
            return True
        except subprocess.TimeoutExpired as ex:
            process.kill()

            if self.settings.ignore_timeout:
                return True
            else:
                raise Exception(f"Timeout during program execution: {ex}")
            
    def exports_data(self) -> bool:
        return False
