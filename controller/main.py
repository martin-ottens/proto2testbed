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

    parser = argparse.ArgumentParser(prog=os.environ.get("CALLER_SCRIPT", sys.argv[0]), 
                                     description="Proto²Testbed Controller")
    
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument("-v", "--verbose", action="count", required=False, default=0,
                               help="-v: Print DEBUG log messages, -vv: Print TRACE log messages")
    common_parser.add_argument("--sudo", action="store_true", required=False, default=False,
                               help="Prepend 'sudo' to all commands (non-interactive), root required otherwise")
    common_parser.add_argument( "-e", "--experiment", required=False, default=None, type=str, 
                               help="Name of experiment series, auto generated if omitted")
    common_parser.add_argument("--influxdb", required=False, default=None, type=str, 
                               help="Path to InfluxDB config, use defaults/environment if omitted")

    subparsers = parser.add_subparsers(title="subcommand", dest="mode", required=True,
                                     description="Subcommand for Proto²Testbed Controller")
    
    # Command "run": Start a testbed run
    run_parser = subparsers.add_parser("run", aliases=["r"], help="Execute a testbed Configuration",
                                       parents=[common_parser])
    run_parser.add_argument("TESTBED_CONFIG", type=str, help="Path to testbed package")
    run_parser.add_argument("--clean", action="store_true", required=False, default=False,
                            help="Clean network interfaces and files.")
    run_parser.add_argument("--interact", "-i", choices=[p.name for p in PauseAfterSteps], 
                            required=False, default=PauseAfterSteps.DISABLE.name, type=str.upper,
                            help="Interact with Conctroller after step is completed")
    run_parser.add_argument("--no_kvm", action="store_true", required=False, default=False,
                            help="Disable KVM virtualization in QEMU")
    run_parser.add_argument("-s", "--skip_integration", action="store_true", required=False, default=False,
                            help="Skip the execution of integrations") 
    run_parser.add_argument("-d", "--dont_store", required=False, default=False, action="store_true", 
                            help="Dont store experiment results to InfluxDB on host")
    run_parser.add_argument("--skip_substitution", action="store_true", required=False, default=False, 
                            help="Skip substitution of placeholders with environment variable values in config")
    run_parser.add_argument("-p", "--preserve", type=str, help="Path for instance data preservation, disabled with omitted",
                            required=False, default=None)

    # Command "clean": Remove dangling testbeds (-a = from all users)
    clean_parser = subparsers.add_parser("clean", aliases=["c"], help="Clean danging testbeds (files, interfaces ...)",
                                       parents=[common_parser])
    clean_parser.add_argument("-a", "--all", required=False, default=False, action="store_true",
                              help="Also clean testbeds from different users")

    # Command "list": List running testbeds and instances (-a = from all users)
    list_parser = subparsers.add_parser("list", aliases=["ls"], help="List running testbeds and instances",
                                        parents=[common_parser])
    list_parser.add_argument("-a", "--all", required=False, default=False, action="store_true",
                             help="Show testbeds from all users")

    # Command "attach": Attach to a running instance (-s = use ssh)
    attach_parser = subparsers.add_parser("attach", aliases=["a"], help="Attach to the tty of an Instance",
                                        parents=[common_parser])
    attach_parser.add_argument("-s", "--ssh", required=False, default=False, action="store_true",
                               help="Use SSH instead of serial connection (if available)")
    
    args = parser.parse_args()

    # Some lazy loading from there for better CLI reactivity
    from cli import CLI
    from utils.settings import CLIParameters, SettingsWrapper

    CLI.setup_early_logging()

    if args.clean:
        from utils.cleanup import delete_residual_parts
        sys.exit(delete_residual_parts())
    
    if args.TESTBED_CONFIG is None:
        parser.error("Argument TESTBED_CONFIG is required.")
        sys.exit(1)

    parameters = CLIParameters()
    if os.path.isabs(args.TESTBED_CONFIG):
        parameters.config = args.TESTBED_CONFIG
    else:
        parameters.config = f"{os.getcwd()}/{args.TESTBED_CONFIG}"

    parameters.interact = PauseAfterSteps[args.interact]
    parameters.sudo_mode = args.sudo
    parameters.disable_kvm = args.no_kvm
    parameters.clean = args.clean
    parameters.dont_use_influx = args.dont_store
    parameters.influx_path = args.influxdb
    parameters.skip_integration = args.skip_integration
    parameters.skip_substitution = args.skip_substitution
    parameters.log_verbose = args.verbose
    parameters.app_base_path = Path(__file__).parent.resolve()
    SettingsWrapper.cli_paramaters = parameters

    if parameters.interact != PauseAfterSteps.DISABLE and not os.isatty(sys.stdout.fileno()):
        logger.error("TTY does not allow user interaction, disabling 'interact' parameter")
        parameters.interact = PauseAfterSteps.DISABLE

    SettingsWrapper.experiment = args.experiment
    if SettingsWrapper.experiment is None:
        SettingsWrapper.experiment = "".join(random.choices(string.ascii_letters + string.digits, k=8))
        if not parameters.dont_use_influx:
            logger.warning(f"InfluxDBAdapter: InfluxDB experiment tag randomly generated -> {SettingsWrapper.experiment}")

    original_uid = os.environ.get("SUDO_UID", None)
    if original_uid is None:
        original_uid = os.getuid()

    import psutil

    SettingsWrapper.executor = original_uid
    SettingsWrapper.main_pid = os.getpid()
    SettingsWrapper.cmdline = " ".join(psutil.Process(SettingsWrapper.main_pid).cmdline())
    SettingsWrapper.unique_run_name = f"{''.join(SettingsWrapper.experiment.split())}-{str(original_uid)}"

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

    if not args.sudo and os.geteuid() != 0:
        logger.critical("Unable to start: You need to be root!")
        sys.exit(1)

    from utils.config_tools import DefaultConfigs
    SettingsWrapper.default_configs = DefaultConfigs("/etc/proto2testbed/proto2testbed_defaults.json")

    script_name = sys.argv[0]

    from controller import Controller

    try:
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

            signal.signal(signal.SIGINT, void_signal_handler)
            signal.signal(signal.SIGTERM, void_signal_handler)
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
