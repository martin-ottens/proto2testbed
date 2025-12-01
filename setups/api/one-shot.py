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

#
# ONE-SHOT API USAGE EXAMPLE
#
# This is a minimal example for the use of Proto²Testbed's API in
# one-shot operation. It runs loads a testbed config from a JSON file,
# starts the testbed, exports the preserved files to a local directory
# and outputs logs and time series data from the InfluxDB to stdout.

# Load Proto²Testbed sources in a hacky way.
import sys
from pathlib import Path
sys.path.insert(0, str(Path("../../controller").resolve()))
from api import Proto2TestbedAPI

TESTBED_PACKAGE = Path(".")

# Instantiate the API object with default settings
api = Proto2TestbedAPI(log_to_influx=True)

# Execute the testbed. Since no testbed config is provided, it will be 
# loaded from within the testbed package (TESTBED_PACKAGE/testbed.json). 
# This method blocks until the testbed completes (or fails). 
# A FullResultWrapper is returned that contains the logs and statuses of all
# testbed components (but no time series data in this case, as these are 
# exported to the InfluxDB). In case of a critical/unrecoverable failure of 
# the testbed, this method raises an TestbedInitializationException or 
# TestbedExecutionException. 
result = api.run_testbed(testbed_package_path=TESTBED_PACKAGE,
                         preserve_path=Path("./out"))

# Check if testbed results a present, output the contents of the 
# FullResultWrapper to stdout. 
if result is None:
    raise Exception("Unable to get testbed result.")

result.dump_state()

# Use the (in this case, since none was provided, randomly generated) experiment 
# tag and testbed config stored in the FullResultWrapper to get the exported
# time series data from the InfluxDB as a list of APISeriesContainer objects.
# Output them to stdout and clean the testbed using the same experiment tag in the
# FullResultWrapper.
print("Results from InfluxDB:", api.export_results_from_wrapper(result))
api.clean_results_from_wrapper(result)

# List all running testbeds, should be an empty list when the destory_testbed 
# method was successful. The testbed was automatically destroyed after
# calling the run_testbed method in one-shot operation.
print("Running testbeds:", api.list_testbeds())
