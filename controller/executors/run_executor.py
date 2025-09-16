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
import sys

from loguru import logger

from executors.base_executor import BaseExecutor
from utils.continue_mode import PauseAfterSteps
from utils.settings import RunParameters
from utils.state_provider import TestbedStateProvider


class RunExecutor(BaseExecutor):
    SUBCOMMAND = "run"
    ALIASES = ["r"]
    HELP = "Execute a testbed"

    def __init__(self, subparser: argparse._SubParsersAction):
        super().__init__(subparser)

        self.subparser.add_argument("TESTBED_CONFIG", type=str, help="Path to testbed package")
        self.subparser.add_argument("--interact", "-i", choices=[p.name for p in PauseAfterSteps], 
                                    required=False, default=PauseAfterSteps.DISABLE.name, type=str.upper,
                                    help="Interact with Controller after step is completed")
        self.subparser.add_argument("--no_kvm", action="store_true", required=False, default=False,
                                    help="Disable KVM virtualization in QEMU")
        self.subparser.add_argument("-s", "--skip_integrations", action="store_true", required=False, default=False,
                                    help="Skip the execution of integrations") 
        self.subparser.add_argument("-d", "--dont_store", required=False, default=False, action="store_true", 
                                    help="Dont store experiment results to InfluxDB on host")
        self.subparser.add_argument("--skip_substitution", action="store_true", required=False, default=False, 
                                    help="Skip substitution of placeholders with environment variable values in config")
        self.subparser.add_argument("-p", "--preserve", type=str, help="Path for instance data preservation, disabled with omitted",
                                    required=False, default=None)

    def invoke(self, args, provider: TestbedStateProvider) -> int:
        parameters = RunParameters()
        if os.path.isabs(args.TESTBED_CONFIG):
            parameters.config = args.TESTBED_CONFIG
        else:
            parameters.config = f"{os.getcwd()}/{args.TESTBED_CONFIG}"

        parameters.interact = PauseAfterSteps[args.interact]
        parameters.disable_kvm = args.no_kvm
        parameters.dont_use_influx = args.dont_store
        parameters.skip_integration = args.skip_integrations
        parameters.skip_substitution = args.skip_substitution
        
        if provider.experiment_generated:
            logger.warning(f"InfluxDBAdapter: InfluxDB experiment tag randomly generated -> {provider.experiment}")
        
        if parameters.interact != PauseAfterSteps.DISABLE and not os.isatty(sys.stdout.fileno()):
            logger.error("TTY does not allow user interaction, disabling 'interact' parameter")
            parameters.interact = PauseAfterSteps.DISABLE
        
        # TODO: Move
        from pathlib import Path
        if args.preserve is not None:
            try:
                parameters.preserve = Path(args.preserve)
                if not bool(parameters.preserve.anchor or parameters.preserve.name):
                    raise Exception("Preserve Path invalid")
            except Exception as e:
                logger.critical("Unable to start: Preserve Path is not valid!")
                return 1
        else:
            parameters.preserve = None

        provider.set_run_parameters(parameters)

        from helper.state_file_helper import StateFileReader
        reader = StateFileReader(provider)
        all_experiments = reader.get_other_experiments(provider.experiment)

        # TODO: Move
        if len(all_experiments) != 0:
            logger.critical(f"Other testbeds with same experiment tag are running:")
            for user, pid in all_experiments.items():
                logger.info(f"- User: {user}, PID: {pid}")
            return 1


        from controller import Controller
        import signal
        try:
            controller = Controller(provider)
        except Exception as ex:
            logger.opt(exception=ex).critical("Error during config initialization")
            return 1

        try:
            status = controller.main()
        except Exception as ex:
            logger.opt(exception=ex).critical("Uncaught Controller Exception")
            status = False
        except KeyboardInterrupt:
            logger.error("Caught keyboard interrupt at top level, forcing shutdown ...")
            controller.interrupted_event.set()
            status = False
        finally:
            def void_signal_handler(signo, _):
                logger.warning(f"Signal {signal.Signals(signo).name} was inhibited during testbed shutdown.")

            signal.signal(signal.SIGINT, void_signal_handler)
            signal.signal(signal.SIGTERM, void_signal_handler)
            was_interrupted = controller.interrupted_event.is_set()
            controller.dismantle(force=was_interrupted)

            restart_requested = controller.request_restart

        if parameters.preserve is not None:
            logger.success(f"Files preserved to '{parameters.preserve}' (if any)")
        
        if not parameters.dont_use_influx:
            logger.success(f"Data series stored with experiment tag '{provider.experiment}' (if any)")

        exit_code = 0
        if status:
            logger.success("Testbed was dismantled!")
            exit_code = 0
        else:
            logger.critical("Testbed was dismantled after error.")
            exit_code = 1

        if restart_requested:
            logger.success("Testbed restart was requested, trying to restart ...")
            exit_code = 254
        
        return exit_code
        
    def requires_priviledges(self) -> bool:
        return True
    
    def dumps_to_state_files(self) -> bool:
        return True
