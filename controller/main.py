#!/usr/bin/python3

import argparse
import sys
import os
import signal
import random
import string

from loguru import logger
from pathlib import Path


if __name__ == "__main__":
    from utils.continue_mode import PauseAfterSteps

    parser = argparse.ArgumentParser(prog=os.environ.get("CALLER_SCRIPT", sys.argv[0]), description="Proto²Testbed Controller")
    parser.add_argument("TESTBED_CONFIG", type=str, help="Path to testbed package")
    parser.add_argument("--clean", action="store_true", required=False, default=False,
                        help="Clean network interfaces before startup (Beware of concurrent testbeds!)")
    parser.add_argument("--interact", "-i", choices=[p.name for p in PauseAfterSteps], 
                        required=False, default=PauseAfterSteps.DISABLE.name, type=str.upper,
                        help="Interact with Conctroller after step is completed")
    parser.add_argument("-v", "--verbose", action="count", required=False, default=0,
                        help="-v: Print DEBUG log messages, -vv: Print TRACE log messages")
    parser.add_argument("-q", "--quiet", action="store_true", required=False, default=False,
                        help="Only print INFO, ERROR, SUCCESS or CRITICAL log messages")
    parser.add_argument("--sudo", action="store_true", required=False, default=False,
                        help="Prepend 'sudo' to all commands (non-interactive), root required otherwise")
    parser.add_argument("--no_kvm", action="store_true", required=False, default=False,
                        help="Disable KVM virtualization in QEMU")
    parser.add_argument("-s", "--skip_integration", action="store_true", required=False, default=False,
                        help="Skip the execution of integrations")
    parser.add_argument( "-e", "--experiment", required=False, default=None, type=str, 
                        help="Name of experiment series, auto generated if omitted")
    parser.add_argument("-d", "--dont_store", required=False, default=False, action="store_true", 
                        help="Dont store experiment results to InfluxDB on host")
    parser.add_argument("--influxdb", required=False, default=None, type=str, 
                        help="Path to InfluxDB config, use defaults/environment if omitted")
    parser.add_argument("--skip_substitution", action="store_true", required=False, default=False, 
                        help="Skip substitution of placeholders with environment variable values in config")
    parser.add_argument("-p", "--preserve", type=str, help="Path for instance data preservation, disabled with omitted",
                        required=False, default=None)
    
    args = parser.parse_args()

    from cli import CLI
    from utils.settings import CLIParameters

    CLI.setup_early_logging()

    parameters = CLIParameters()
    if os.path.isabs(args.TESTBED_CONFIG):
        parameters.config = args.TESTBED_CONFIG
    else:
        parameters.config = f"{os.getcwd()}/{args.TESTBED_CONFIG}"

    parameters.interact = PauseAfterSteps[args.interact]
    parameters.sudo_mode = args.sudo
    parameters.disable_kvm = args.no_kvm
    parameters.clean = args.clean
    parameters.experiment = args.experiment
    parameters.dont_use_influx = args.dont_store
    parameters.influx_path = args.influxdb
    parameters.skip_integration = args.skip_integration
    parameters.skip_substitution = args.skip_substitution
    parameters.log_verbose = args.verbose
    parameters.app_base_path = Path(__file__).parent.resolve()

    if parameters.interact != PauseAfterSteps.DISABLE and not os.isatty(sys.stdout.fileno()):
        logger.error("TTY does not allow user interaction, disabling 'interact' parameter")
        parameters.interact = PauseAfterSteps.DISABLE

    if parameters.experiment is None:
        parameters.experiment = "".join(random.choices(string.ascii_letters + string.digits, k=8))
        if not parameters.dont_use_influx:
            logger.warning(f"InfluxDBAdapter: InfluxDB experiment tag randomly generated -> {parameters.experiment}")

    original_uid = os.environ.get("SUDO_UID", None)
    if original_uid is None:
        original_uid = os.getuid()

    parameters.unique_run_name = f"{''.join(parameters.experiment.split())}-{str(original_uid)}"

    if args.preserve is not None:
        try:
            parameters.preserve = Path(args.preserve)
            if not bool(parameters.preserve.anchor or parameters.preserve.name):
                raise Exception("Preserve Path invalid")
        except Exception as e:
            logger.critical("Unable to start: Preserve Path is not valid!")
            sys.exit(1)
    else:
        parameters.preserve = None

    from utils.settings import CLIParameters, SettingsWrapper
    from utils.config_tools import DefaultConfigs

    SettingsWrapper.cli_paramaters = parameters

    if not args.sudo and os.geteuid() != 0:
        logger.critical("Unable to start: You need to be root!")
        sys.exit(1)

    SettingsWrapper.default_configs = DefaultConfigs("/etc/proto2testbed/proto2testbed_defaults.json")

    script_name = sys.argv[0]

    from controller import Controller
    from utils.pidfile import PidFile

    try:
        with PidFile(f"/tmp/ptb-{parameters.unique_run_name}.pid", name=script_name):

            try:
                controller = Controller()
            except Exception as ex:
                logger.opt(exception=ex).critical("Error during config initialization")
                sys.exit(1)

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

                #signal.signal(signal.SIGINT, void_signal_handler)
                #signal.signal(signal.SIGTERM, void_signal_handler)
                was_interrupted = controller.interrupted_event.is_set()
                controller.dismantle(force=was_interrupted)
    except Exception as ex:
        logger.opt(exception=ex).critical(f"Another instance of '{script_name}' is still running.")
        sys.exit(1)

    if status:
        logger.success("Testbed was dismantled!")
        sys.exit(0)
    else:
        logger.critical("Testbed was dismantled after error.")
        sys.exit(1)
