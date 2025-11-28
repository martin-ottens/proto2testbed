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
from utils.settings import TestbedConfig

TESTBED_PACKAGE = Path(".")

# Instanciate the API class with some default settings
api = Proto2TestbedAPI(log_to_influx=True, 
                       skip_integration=True)

# Load the testbed config from JSON file. It is also
# possible (and the "more intended way") to create a 
# TestbedConfig object in the programm itself.
config = api.load_testbed_config_from_package(TESTBED_PACKAGE)

# Execute the testbed with the loaded TestbedConfig. Create
# a checkpoint that can be used to execute different experiments
# with the same testbed setup in a looped operation. This
# method blocks until the testbed completes (or fails), but with
# use_checkpoints before it is dismantled.
result = api.run_testbed(testbed_package_path=TESTBED_PACKAGE,
                         testbed_config=config,
                         use_checkpoints=True)

# Manually dismantle the testbed
api.destroy_testbed()

# Get the testbed logs, instance and application status reports in a
# machine readable format, output to stdout
if result is None:
    raise Exception("Unable to get testbed result.")

result.dump_state()

# Set the previously randomly generated experiment tag to the API instance
# to obtain the data series results. Clean results afterwards
print("Results from InfluxDB:", api.export_results(result.experiment_tag, config))
api.clean_results(result.experiment_tag)

# List all running testbeds, should be an empty list when the 
# destory_testbed was sucessfull
print("Running testbeds:", api.list_testbeds())
