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

import os

from filelock import FileLock

from constants import GLOBAL_LOCKFILE


class StateLock:
    def __init__(self, statefile_base: str) -> None:
        os.makedirs(statefile_base, exist_ok=True, mode=0o777)
        self.lock = FileLock(statefile_base / GLOBAL_LOCKFILE)
    
    def lock_statefile(self) -> None:
        self.lock.acquire()

    def unlock_statefile(self) -> None:
        self.lock.release()

    def __enter__(self):
        self.lock_statefile()
        return self

    def __exit__(self, exception_type, exception_value, exception_traceback):
        self.unlock_statefile()
