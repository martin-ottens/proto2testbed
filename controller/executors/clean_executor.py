#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2024-2026 Martin Ottens
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

from loguru import logger

from executors.base_executor import BaseExecutor
from utils.state_provider import TestbedStateProvider


class CleanExecutor(BaseExecutor):
    SUBCOMMAND = "clean"
    ALIASES = ["c"]
    HELP = "Clean results from a testbed execution"

    def __init__(self, subparser: argparse._SubParsersAction):
        super().__init__(subparser)
        self.subparser.add_argument("--all", action="store_true", required=False, default=False, 
                                    help="Delete all measurements from database")

    def invoke(self, args, provider: TestbedStateProvider) -> int:
        from cli import CLI
        from helper.export_helper import ResultExportHelper

        CLI(provider)
        helper = ResultExportHelper(provider.testbed_config, None, provider)

        if provider.experiment_generated and not args.all:
            logger.critical(f"No experiment tag was specified, use -e to specify an experiment tag.")
            return 1
        

        if not args.all:
            logger.info(f"Deleting all result data with experiment tag '{provider.experiment}' from database '{helper.get_selected_database()}'")
            if not helper.clear_results_for_experiment(provider.experiment):
                return 1
            
            logger.success(f"All data for experiment tag '{provider.experiment}' deleted")
            return 0
        else:
            logger.info(f"Deleting ALL data from database '{helper.get_selected_database()}'")
            if not helper.clear_all_results():
                return 1
            
            logger.success(f"Deleted ALL data from database '{helper.get_selected_database()}'")
            return 0
