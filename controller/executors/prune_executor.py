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
import os

from loguru import logger

from executors.base_executor import BaseExecutor
from utils.state_provider import TestbedStateProvider


class PruneExecutor(BaseExecutor):
    SUBCOMMAND = "prune"
    ALIASES = ["p"]
    HELP = "Clean dangling testbed parts (files, interfaces etc.)"

    def __init__(self, subparser: argparse._SubParsersAction):
        super().__init__(subparser)

        self.subparser.add_argument("--all", required=False, default=False, action="store_true",
                                    help="Also clean testbeds from different users")
        self.subparser.add_argument("--interfaces", required=False, default=False, action="store_true",
                                    help="Clean dangling interfaces, ")

    def invoke(self, args, provider: TestbedStateProvider) -> int:
        from cli import CLI
        from state_manager import InstanceState
        from helper.state_file_helper import StateFileReader
        from helper.network_helper import NetworkBridge

        CLI(provider, None)

        statefile_reader = StateFileReader(provider)
        all_states = statefile_reader.get_states(filter_owned_by_executor=(not args.all))

        running_interfaces = NetworkBridge.get_running_interfaces()

        def delete_interface(target: str, fail_silent: bool = False):
            if target not in running_interfaces:
                logger.debug(f"Interface '{interface}' does not exist.")
                return
            
            try:
                if NetworkBridge.cleanup_interface(target, fail_silent):
                    logger.info(f"Deleted Interface '{target}' from non-running testbed.")
            except Exception as ex:
                logger.opt(exception=ex).error(f"Unable to delete interface '{target}'")

        logger.info("Deleting orphaned testbeds ...")
        # Clear interchange dir of invalid testbeds and interchange dir and 
        # interfaces of non-running testbeds 
        for entry in all_states:
            if entry.contents is None:
                if InstanceState.clean_interchange_dir(os.path.dirname(entry.filepath)):
                    logger.info(f"Deleted interchange dir without contents: '{entry.filepath}'")
                continue
            
            if StateFileReader.is_process_running(entry.contents):
                logger.debug(f"Skipping state '{entry.filepath}': Testbed is running.")
                continue

            for interface in entry.contents.interfaces:
                delete_interface(interface.bridge_dev)
                delete_interface(interface.tap_dev)
            
            if InstanceState.clean_interchange_dir(os.path.dirname(entry.filepath)):
                logger.info(f"Deleted interchange dir: '{entry.filepath}'")

        if not args.interfaces:
            return 0
        
        logger.info("Deleting dangling interfaces ...")
        # Reload updated states -> Cleaned up all "unwanted" states before
        statefile_reader.reload()
        all_states = statefile_reader.get_states()

        known_interfaces = set()
        for entry in all_states:
            for interface in entry.contents.interfaces:
                known_interfaces.add(interface.tap_dev)
                known_interfaces.add(interface.bridge_dev)
        
        for interface in NetworkBridge.get_running_interfaces():
            if interface in known_interfaces:
                continue

            delete_interface(interface, True)

        return 0

    def requires_priviledges(self) -> bool:
        return True
