#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2024 Martin Ottens
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

from utils.settings import CommonSettings
from executors.base_executor import BaseExecutor

class ListExecutor(BaseExecutor):
    SUBCOMMAND = "list"
    ALIASES = ["ls"]
    HELP = "List all running testbeds an their instances"

    def __init__(self, subparser: argparse._SubParsersAction):
        super().__init__(subparser)
        self.subparser.add_argument("-a", "--all", required=False, default=False, action="store_true",
                                    help="Show testbeds from all users")

    def invoke(self, args) -> int:
        from cli import CLI
        from helper.state_file_helper import StateFileReader

        CLI(CommonSettings.log_verbose, None)

        statefile_reader = StateFileReader()
        states = statefile_reader.get_states(filter_owned_by_executor=(not args.all))

        # (uid, experiment) -> [states]
        experiment_map = {}
        # (uid, experiment) -> {name, interface}
        network_map = {}
        total = 0
        for state in states:
            if state.contents is None:
                logger.warning(f"State file '{state.filepath}': Unable to obtain details.")
            else:
                indexer = (state.contents.executor, state.contents.experiment)
                if indexer not in experiment_map.keys():
                    experiment_map[indexer] = []

                if indexer not in network_map.keys():
                    network_map[indexer] = {}
                
                experiment_map[indexer].append(state.contents)
                
                for interface in state.contents.interfaces:
                    if interface.bridge_name not in network_map[indexer].keys():
                        network_map[indexer][interface.bridge_name] = interface

                total += 1
        
        if total == 0:
            logger.warning("No experiments are running for that search criteria.")
            return 0

        logger.success(f"Listing {len(experiment_map)} experiment(s) for {'whole system' if args.all else 'current user'}")
        for experiment_index, (indexer, state) in enumerate(experiment_map.items(), start=1):
            is_last_experiment = (experiment_index == len(experiment_map.keys()))
            uid, experiment = indexer
            prefix_experiment = "├─" if not is_last_experiment else "└─"
            running = StateFileReader.is_process_running(state[0])
            logger.opt(ansi=True).info(f"{prefix_experiment} <u>Experiment: {experiment}, Owner: {StateFileReader.get_name(uid)}, Status: {'<green>running</green>' if running else '<red>dangling</red>'} (PID {state[0].main_pid})</u>")
            prefix_networks = "│  ├─" if not is_last_experiment else "   ├─"
            logger.info(f"{prefix_networks} Networks ({len(network_map[indexer])}):")
            for network_index, network in enumerate(network_map[indexer].values(), start=1):
                is_last_network = (network_index == len(network_map[indexer]))
                prefix_network = "│  │ " if not is_last_experiment else "   │ "
                prefix_network += " ├─" if not is_last_network else " └─"
                logger.opt(ansi=True).info(f"{prefix_network} <blue>Bridge: {network.bridge_name}</blue> ({network.bridge_dev}) " 
                            + (f"─> host ports: <yellow>{' '.join(network.host_ports)}</yellow>" if network.host_ports is not None and len(network.host_ports) != 0 else ""))

            prefix_instances = "│  └─" if not is_last_experiment else "   └─"
            logger.info(f"{prefix_instances} Instances ({len(state)}):")
            for instance_index, instance in enumerate(state, start=1):
                is_last_instance = (instance_index == len(state))
                prefix_instance = "│  " if not is_last_experiment else "   "
                prefix_instance += "   ├─" if not is_last_instance else "   └─"

                logger.opt(ansi=True).info(f"{prefix_instance} <green>Instance: {instance.instance}</green> ({instance.uuid}) {'' if not instance.mgmt_ip else f'(IP: {instance.mgmt_ip})'}")

                sorted_if = sorted(instance.interfaces)
                for interface_index, interface in enumerate(sorted_if, start=1):
                    is_last_interface = (interface_index == len(sorted_if))
                    prefix_interface = "│  " if not is_last_experiment else "   "
                    prefix_interface += "   │ " if not is_last_instance else "     "
                    prefix_interface += " ├─" if not is_last_interface else " └─"
                    
                    logger.opt(ansi=True).info(f"{prefix_interface} {interface.tap_index}: Interface {interface.tap_dev} ({interface.interface_on_instance}, {interface.tap_mac}) ─> bridge <blue>{interface.bridge_name}</blue>")

        return 0
