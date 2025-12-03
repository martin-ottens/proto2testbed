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

from enum import Enum


class PauseAfterSteps(Enum):
    SETUP = 1
    INIT = 2
    EXPERIMENT = 3
    FINISH = 4
    DISABLE = 5

    @classmethod
    def get_selectable(cls):
        return [cls.SETUP, cls.INIT, cls.EXPERIMENT, cls.DISABLE]


class ContinueMode(Enum):
    EXIT = "exit"
    RESTART = "restart"
    CONTINUE_TO = "continue_to"


class CLIContinue:
    def __init__(self, stopped_at: PauseAfterSteps):
        self.stopped_at = stopped_at
        self.mode = ContinueMode.EXIT
        self.pause = PauseAfterSteps.DISABLE

    def update(self, mode: ContinueMode, pause: PauseAfterSteps = PauseAfterSteps.DISABLE) -> bool:
        if self.stopped_at.value >= pause.value:
            return False
        
        self.mode = mode
        self.pause = pause
        return True
