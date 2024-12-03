import argparse

from loguru import logger

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
        from helper.state_file_helper import StateFileReader

        def get_name(uid: int) -> str:
            import pwd
            try:
                ui = pwd.getpwuid(uid)
                return ui.pw_name
            except KeyError:
                return str(uid)

        statefile_reader = StateFileReader()
        states = statefile_reader.get_states(owned_by_executor=(not args.all))

        # experiment -> [states]
        experiment_map = {}
        total = 0
        for state in states:
            if state.contents is None:
                logger.warning(f"State file '{state.filepath}': Unable to obtain details.")
            else:
                indexer = (state.contents.executor, state.contents.experiment)
                if indexer not in experiment_map.keys():
                    experiment_map[indexer] = []
                
                experiment_map[indexer].append(state.contents)
                total += 1
        
        if total == 0:
            logger.warning("No experiments are running for that search criteria.")
            return 0

        logger.info(f"Listing {total} experiments for {'whole system' if args.all else 'current user'}")

        for experiment_index, (indexer, state) in enumerate(experiment_map.items(), start=1):
            is_last_experiment = (experiment_index == len(experiment_map.keys()))
            uid, experiment = indexer
            prefix_experiment = "├─" if not is_last_experiment else "└─"
            running = StateFileReader.is_process_running(state[0])
            logger.info(f"{prefix_experiment} Experiment: {experiment}, Owner: {get_name(uid)}, Status: {'running' if running else 'dangling'}")
            for instance_index, instance in enumerate(state, start=1):
                is_last_instance = (instance_index == len(state))
                prefix_instance = " │ " if not is_last_experiment else "   "
                prefix_instance += " ├─" if not is_last_instance else " └─"

                logger.info(f"{prefix_instance} Instance: {instance.instance} ({instance.uuid}) {'' if not instance.mgmt_ip else f'(IP: {instance.mgmt_ip})'}")

                sorted_if = sorted(instance.interfaces)
                for interface_index, interface in enumerate(sorted_if, start=1):
                    is_last_interface = (interface_index == len(sorted_if))
                    prefix_interface = " │ " if not is_last_experiment else "   "
                    prefix_interface += " │ " if not is_last_instance else "   "
                    prefix_interface += " ├─" if not is_last_interface else " └─"
                    
                    logger.info(f"{prefix_interface} {interface.tap_index}: Interface {interface.tap_dev} ({interface.tap_mac}) conncted to bridge {interface.bridge_name} ({interface.bridge_dev})")

        return 0
        
