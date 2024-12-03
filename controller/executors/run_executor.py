import argparse
import os
import sys

from loguru import logger

from executors.base_executor import BaseExecutor
from utils.continue_mode import PauseAfterSteps
from utils.settings import CommonSetings, RunCLIParameters, TestbedSettingsWrapper

class RunExecutor(BaseExecutor):
    SUBCOMMAND = "run"
    ALIASES = ["r"]
    HELP = "Execute a testbed"

    def __init__(self, subparser: argparse._SubParsersAction):
        super().__init__(subparser)

        self.subparser.add_argument("TESTBED_CONFIG", type=str, help="Path to testbed package")
        self.subparser.add_argument("--clean", action="store_true", required=False, default=False,
                                    help="Clean network interfaces and files.")
        self.subparser.add_argument("--interact", "-i", choices=[p.name for p in PauseAfterSteps], 
                                    required=False, default=PauseAfterSteps.DISABLE.name, type=str.upper,
                                    help="Interact with Conctroller after step is completed")
        self.subparser.add_argument("--no_kvm", action="store_true", required=False, default=False,
                                    help="Disable KVM virtualization in QEMU")
        self.subparser.add_argument("-s", "--skip_integration", action="store_true", required=False, default=False,
                                    help="Skip the execution of integrations") 
        self.subparser.add_argument("-d", "--dont_store", required=False, default=False, action="store_true", 
                                    help="Dont store experiment results to InfluxDB on host")
        self.subparser.add_argument("--skip_substitution", action="store_true", required=False, default=False, 
                                    help="Skip substitution of placeholders with environment variable values in config")
        self.subparser.add_argument("-p", "--preserve", type=str, help="Path for instance data preservation, disabled with omitted",
                                    required=False, default=None)

    def invoke(self, args) -> int:
        parameters = RunCLIParameters()
        if os.path.isabs(args.TESTBED_CONFIG):
            parameters.config = args.TESTBED_CONFIG
        else:
            parameters.config = f"{os.getcwd()}/{args.TESTBED_CONFIG}"

        parameters.interact = PauseAfterSteps[args.interact]
        parameters.disable_kvm = args.no_kvm
        parameters.dont_use_influx = args.dont_store
        parameters.skip_integration = args.skip_integration
        parameters.skip_substitution = args.skip_substitution
        
        if CommonSetings.experiment_generated:
            logger.warning(f"InfluxDBAdapter: InfluxDB experiment tag randomly generated -> {CommonSetings.experiment}")
        
        if parameters.interact != PauseAfterSteps.DISABLE and not os.isatty(sys.stdout.fileno()):
            logger.error("TTY does not allow user interaction, disabling 'interact' parameter")
            parameters.interact = PauseAfterSteps.DISABLE
        
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

        TestbedSettingsWrapper.cli_paramaters = parameters

        from controller import Controller
        import signal
        try:
            controller = Controller()
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

        if parameters.preserve is not None:
            logger.success(f"Files preserved to '{parameters.preserve}' (if any)")
        
        if not parameters.dont_use_influx:
            logger.success(f"Data series stored with experiment tag '{CommonSetings.experiment}' (if any)")

        if status:
            logger.success("Testbed was dismantled!")
            return 0
        else:
            logger.critical("Testbed was dismantled after error.")
            return 0
        
    def requires_priviledges(self) -> bool:
        return True
