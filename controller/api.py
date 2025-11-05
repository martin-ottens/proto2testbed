#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2025 Martin Ottens
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


from typing import Optional

from utils.settings import TestbedConfig, RunParameters
from full_result_wrapper import FullResultWrapper

class Proto2TestbedAPI:
    def __init__() -> None:
        pass

    def set_testbed_config(config: TestbedConfig) -> None:
        pass

    def run_testbed(parameters: RunParameters) -> Optional[FullResultWrapper]:
        pass

    def list_testbeds() -> None:
        pass

    def export_results() -> None:
        pass
