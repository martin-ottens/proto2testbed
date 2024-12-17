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

import argparse

from abc import ABC, abstractmethod

class BaseExecutor(ABC):
    SUBCOMMAND = "##DONT_LOAD##"
    ALIASES = []
    HELP = "I'm an abstract base class"

    def __init__(self, subparser: argparse._SubParsersAction):
        self.subparser = subparser

    @abstractmethod
    def invoke(self, args) -> int:
        pass

    def requires_priviledges(self) -> bool:
        return False
