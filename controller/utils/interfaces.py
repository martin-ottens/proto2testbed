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

from abc import ABC, abstractmethod

class NamedInstance(ABC):
    @abstractmethod
    def get_name(self) -> str:
        pass

class Dismantable(NamedInstance):
    @abstractmethod
    def dismantle(self, force: bool = False) -> None:
        pass

    def dismantle_parallel(self) -> bool:
        return False
