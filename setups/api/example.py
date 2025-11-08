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
from utils.settings import TestbedConfig, RunParameters

TESTBED_PACKAGE = "."

# Instanciate the API class
api = Proto2TestbedAPI(log_to_influx=True)

# Load the testbed config from JSON file and update the API instance
# experiment tag will be auto generated for this run. It is also
# possible (and the "more intended way") to create a TestbedConfig 
# object in the programm itsel.
config = api.load_testbed_config_from_package(TESTBED_PACKAGE)
api.set_testbed_config(config)

# Execute the testbed with specific run parameters
parameters = RunParameters(skip_integration=True)
result = api.run_testbed(TESTBED_PACKAGE, parameters)

# Get the testbed logs, instance and application status reports in a
# machine readable format, output to stdout
if result is None:
    raise Exception("Unable to get testbed result.")

result.dump_state()

# Set the previously randomly generated experiment tag to the API instance
# to obtain the data series results. Clean results afterwards
api.set_experiment_tag(result.experiment_tag)
print("Results from InfluxDB:", api.export_results())
api.clean_results()

# List all running testbeds
print("Running testbeds:", api.list_testbeds())
