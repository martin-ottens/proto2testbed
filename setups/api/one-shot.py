#!/usr/bin/python3
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

# Load Proto²Testbed sources
import sys
from pathlib import Path
sys.path.insert(0, str(Path("../../controller").resolve()))

from api import Proto2TestbedAPI

TESTBED_PACKAGE = Path(".")

# Instanciate the API class with some default settings
api = Proto2TestbedAPI(log_to_influx=True, 
                       skip_integration=True)

# Execute the testbed with the loaded TestbedConfig. This
# method blocks until the testbed completes (or fails).
# The testbed config is autoloaded from TESTBED_PACKAGE/testbed.json.
result = api.run_testbed(testbed_package_path=TESTBED_PACKAGE,
                         preserve_path=Path("./out"))

# Get the testbed logs, instance and application status reports in a
# machine readable format, output to stdout
if result is None:
    raise Exception("Unable to get testbed result.")

result.dump_state()

# Set the previously randomly generated experiment tag to the API instance
# to obtain the data series results. Clean results afterwards
print("Results from InfluxDB:", api.export_results_from_wrapper(result))
api.clean_results_from_wrapper(result)

# List all running testbeds, should be an empty list when the 
# destory_testbed was sucessfull
print("Running testbeds:", api.list_testbeds())
