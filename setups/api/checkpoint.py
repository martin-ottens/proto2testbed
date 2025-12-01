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
# CHECKPOINT API USAGE EXAMPLE
#
# Make sure to understand one-shot.py first.
# This example runs the testbed twice, resetting it to a checkpoint after the
# testbed initialization between both runs. The experiment tag, Applications 
# to be executed and preserve path are changed between the testbed runs. 
# Data is exported as in the one shot operation example.

# Load Proto²Testbed sources in a hacky way.
import sys
from pathlib import Path
sys.path.insert(0, str(Path("../../controller").resolve()))
from api import Proto2TestbedAPI
from utils.settings import TestbedConfig

TESTBED_PACKAGE = Path(".")

# Change all "run-program" Applications in the TestbedConfig object
def alter_testbed_config(config: TestbedConfig, i: int) -> None:
    for instance in config.instances:
        for application in instance.applications:
            if application.application != "run-program":
                continue
            application.settings["environment"]["VALUE"] = f"Experiment {i}"

# Instantiate the API class with some default settings and load the testbed 
# config JSON file from the testbed package to a TestbedConfig object.
api = Proto2TestbedAPI(log_to_influx=True, 
                       skip_integration=True)
config = api.load_testbed_config_from_package(testbed_package_path=TESTBED_PACKAGE)

for i in range(1, 3):
    print("---------------------------------------")
    print("---------------------------------------")
    print(f"-------- STARTING TESTBED RUN {i} -------")
    print("---------------------------------------")
    print("---------------------------------------")
    alter_testbed_config(config, i)

    result = api.run_testbed(testbed_config=config,
                             testbed_package_path=TESTBED_PACKAGE,
                             use_checkpoints=True,
                             preserve_path=Path(f"./out{i}"),
                             experiment_tag=f"checkpoint{i}")
    
    result.dump_state()
    print("Results from InfluxDB:", api.export_results(experiment_tag=result.experiment_tag,
                                                       testbed_config=result.testbed_config))
    api.clean_results(experiment_tag=result.experiment_tag)

    print("Running testbeds:", api.list_testbeds())

api.destroy_testbed()
print("Running testbeds:", api.list_testbeds())
