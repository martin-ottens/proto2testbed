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

import argparse

from loguru import logger

from executors.base_executor import BaseExecutor
from utils.settings import CommonSettings


class CleanExecutor(BaseExecutor):
    SUBCOMMAND = "clean"
    ALIASES = ["c"]
    HELP = "Clean results from a testbed execution"

    def __init__(self, subparser: argparse._SubParsersAction):
        super().__init__(subparser)
        self.subparser.add_argument("--all", action="store_true", required=False, default=False, 
                                    help="Delete all measurements from database")

    def invoke(self, args) -> int:
        from cli import CLI
        from utils.influxdb import InfluxDBAdapter

        CLI(CommonSettings.log_verbose, None)

        if CommonSettings.experiment_generated and not args.all:
            logger.critical(f"No experiment tag was specified, use -e to specify an experiment tag.")
            return 1
        
        adapter = InfluxDBAdapter(warn_on_no_database=True)
        client = adapter.get_access_client()
        if client is None:
            raise Exception("Unable to create InfluxDB access client")

        if not args.all:
            logger.info(f"Deleting all result data with experiment tag '{CommonSettings.experiment}' from database '{adapter.get_selected_database()}'")
            try:
                client.delete_series(tags={"experiment": CommonSettings.experiment})
            except Exception as ex:
                logger.opt(exception=ex).critical(f"Unable to delete experiment tag '{CommonSettings.experiment}' from database '{adapter.get_selected_database()}'")
                return 1
            finally:
                adapter.close_access_client()
            
            logger.success(f"All data for experiment tag '{CommonSettings.experiment}' deleted")
            return 0
        else:
            logger.info(f"Deleting ALL data from database '{adapter.get_selected_database()}'")
            try:
                for measurement in client.get_list_measurements():
                    name = measurement["name"]
                    logger.debug(f"Deleting measurement '{name}'")
                    client.drop_measurement(name)
            except Exception as ex:
                logger.opt(exception=ex).critical(f"Error deleting ALL dara from database '{adapter.get_selected_database()}'")
                return 1
            finally:
                adapter.close_access_client()
            
            logger.success(f"Deleted ALL data from database '{adapter.get_selected_database()}'")
            return 0
