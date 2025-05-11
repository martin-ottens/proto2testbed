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

from typing import Any, Optional

from common.interfaces import JSONSerializer

class ApplicationSettings(ABC):
    pass


class ApplicationConfig(JSONSerializer):
    def __init__(self, name: str, application: str, delay: int = 0, 
                 runtime: int = 30, dont_store: bool = False, 
                 load_from_instance: bool = False, settings = Optional[Any]) -> None:
        self.name: str = name
        self.delay: int = delay
        self.runtime: int = runtime
        self.dont_store: bool = dont_store
        self.application: str = application
        self.load_from_instance: bool = load_from_instance
        self.settings: ApplicationConfig = settings
