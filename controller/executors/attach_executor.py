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
from utils.state_provider import TestbedStateProvider


class AttachExecutor(BaseExecutor):
    SUBCOMMAND = "attach"
    ALIASES = ["a"]
    HELP = "Attach to an Instance"

    def __init__(self, subparser: argparse._SubParsersAction):
        super().__init__(subparser)
        self.subparser.add_argument("INSTANCE", type=str, help="The instance to attach to")
        self.subparser.add_argument("-s", "--ssh", required=False, default=False, action="store_true",
                                    help="Use SSH instead of serial connection (if available)")
        self.subparser.add_argument("-u", "--user", required=False, default="root",
                                    help="User for the SSH login (requires --ssh to take effect)")
        self.subparser.add_argument("-o", "--others", required=False, default=False, action="store_true",
                                    help="Also allow to connect to instances started by other users")

    def invoke(self, args, provider: TestbedStateProvider) -> int:
        from constants import INSTANCE_TTY_SOCKET_PATH, MACHINE_STATE_FILE
        from helper.state_file_helper import StateFileReader
        from cli import CLI
        import os

        cli_handler = CLI(provider)

        statefile_reader = StateFileReader(provider)
        all_states = statefile_reader.get_states(filter_running=True,
                                          filter_owned_by_executor=(not args.others))

        connect_to = None
        if provider.experiment_generated:
            available = []
            for entry in all_states:
                if entry.contents is None:
                    continue

                if entry.contents.instance == args.INSTANCE:
                    available.append(entry)

            if len(available) == 1:
                connect_to = available[0]
            elif len(available) > 1:
                logger.error(f"Instance '{args.INSTANCE}' was found in multiple testbed runs, specify an experiment tag using -e <tag>:")
                for other in available:
                    logger.error(f"- {other.contents.experiment} (Owner: {StateFileReader.get_name(other.contents.executor)})")
                return 1
        else:
            for entry in all_states:
                if entry.contents is None:
                    continue

                if entry.contents.instance != args.INSTANCE:
                    continue

                if entry.contents.experiment == provider.experiment:
                    connect_to = entry
                    break

        if connect_to is None:
            logger.warning(f"No instance found matching that search criteria.")
            return 1

        if args.ssh:
            mgmt_ip = connect_to.contents.mgmt_ip
            if mgmt_ip is None or mgmt_ip == "":
                logger.error(f"Unable to attach to instance '{connect_to.contents.instance}': Management network not enabled.")
                return 1

            if "/" in mgmt_ip:
                mgmt_ip, _ = mgmt_ip.split("/", maxsplit=1)

            logger.success(f"Attaching to instance '{connect_to.contents.instance}' from experiment '{connect_to.contents.experiment}' via SSH")
            logger.success(f"Use CRTL + D or 'exit' in shell to detach from instance.")
            logger.debug(f"Using IP address for connection: {mgmt_ip}, User: {args.user}")
            cli_handler.attach_to_ssh(f"{args.user}@{mgmt_ip}")

        else:
            uds_path = connect_to.filepath
            if MACHINE_STATE_FILE in uds_path:
                uds_path = os.path.dirname(uds_path)

            uds_path = os.path.join(uds_path, INSTANCE_TTY_SOCKET_PATH)

            logger.success(f"Attaching to instance '{connect_to.contents.instance}' from experiment '{connect_to.contents.experiment}' via serial TTY")
            logger.success(f"Use CRTL + ] to detach from instance.")
            logger.debug(f"Using UDS file for connection: {uds_path}")
            cli_handler.attach_to_tty(uds_path)
            print("")

        return 0
