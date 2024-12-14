import argparse
import os

from loguru import logger

from executors.base_executor import BaseExecutor
from utils.settings import CommonSettings

class PruneExecutor(BaseExecutor):
    SUBCOMMAND = "prune"
    ALIASES = ["p"]
    HELP = "Clean dangling testbed parts (files, interfaces etc.)"

    def __init__(self, subparser: argparse._SubParsersAction):
        super().__init__(subparser)

        self.subparser.add_argument("-a", "--all", required=False, default=False, action="store_true",
                                    help="Also clean testbeds from different users")
        self.subparser.add_argument("-i", "--interfaces", required=False, default=False, action="store_true",
                                    help="Clean danging interfaces, ")

    def invoke(self, args) -> int:
        from cli import CLI
        from state_manager import MachineState
        from helper.state_file_helper import StateFileReader
        from helper.network_helper import NetworkBridge

        CLI(CommonSettings.log_verbose, None)

        statefile_reader = StateFileReader()
        all = statefile_reader.get_states(filter_owned_by_executor=(not args.all))

        running_interfaces = NetworkBridge.get_running_interfaces()

        def delete_interface(interface: str, fail_silent: bool = False):
            if interface not in running_interfaces:
                logger.debug(f"Interface '{interface}' does not exist.")
                return
            
            try:
                if NetworkBridge.cleanup_interface(interface, fail_silent):
                    logger.info(f"Deleted Interface '{interface}' from non-running testbed.")
            except Exception as ex:
                logger.opt(exception=ex).error(f"Unable to delete interface '{interface}'")

        logger.info("Deleting orphaned testbeds ...")
        # Clear interchange dir of invalid testbeds and interchange dir and 
        # interfaces of non-running testbeds 
        for entry in all:
            if entry.contents is None:
                if MachineState.clean_interchange_dir(os.path.dirname(entry.filepath)):
                    logger.info(f"Deleted interchange dir without contents: '{entry.filepath}'")
                continue
            
            if StateFileReader.is_process_running(entry.contents):
                logger.debug(f"Skipping state '{entry.filepath}': Testbed is running.")
                continue

            for interface in entry.contents.interfaces:
                delete_interface(interface.bridge_dev)
                delete_interface(interface.tap_dev)
            
            if MachineState.clean_interchange_dir(os.path.dirname(entry.filepath)):
                logger.info(f"Deleted interchange dir: '{entry.filepath}'")

        if not args.interfaces:
            return 0
        
        logger.info("Deleting dangling interfaces ...")
        # Reload updatetd states -> Cleaned up all "unwanted" states before
        statefile_reader.reload()
        all = statefile_reader.get_states()

        known_interfaces = set()
        for entry in all:
            for interface in entry.contents.interfaces:
                known_interfaces.add(interface.tap_dev)
                known_interfaces.add(interface.bridge_dev)
        
        for interface in NetworkBridge.get_running_interfaces():
            if interface in known_interfaces:
                continue

            delete_interface(interface, True)
    
    
    def requires_priviledges(self) -> bool:
        return True
