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

from abc import ABC
from enum import Enum

from typing import Any, Optional, List

from common.interfaces import JSONMessage


class ApplicationSettings(ABC):
    pass


class AppStartStatus(Enum):
    START = "started"
    FINISH = "finished"
    
    @staticmethod
    def from_str(status: str):
        try: return AppStartStatus(status)
        except Exception:
            raise Exception(f"Unknown AppStartStatus '{status}'")

    def __str__(self) -> str:
        return str(self.value)


class DependentAppStartConfig:
    def __init__(self, at: str, instance: str, application: str) -> None:
        self.at: AppStartStatus = AppStartStatus(at)
        self.instance = instance
        self.application = application


class ApplicationConfig(JSONMessage):
    def __init__(self, name: str, application: str, delay: int = 0, 
                 runtime: int = 30, dont_store: bool = False, 
                 load_from_instance: bool = False, 
                 depends = Optional[Any], settings = Optional[Any]) -> None:
        if "@" in name:
            raise Exception(f"Application name '{name}' contains the reserved '@' character.")

        self.name: str = name
        self.delay: int = delay
        self.runtime: int = runtime
        self.dont_store: bool = dont_store
        self.application: str = application
        self.load_from_instance: bool = load_from_instance
        self.settings: ApplicationConfig = settings
        self.depends: List[DependentAppStartConfig] | List[str] =  []

        if isinstance(depends, list):
            for start_config in depends:
                self.depends.append(DependentAppStartConfig(**start_config))
        elif isinstance(depends, dict):
            self.depends.append(DependentAppStartConfig(**depends))
