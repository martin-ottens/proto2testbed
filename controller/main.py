#!/usr/bin/python3

import argparse
import sys
import os

from loguru import logger
from pathlib import Path


from controller import Controller
from utils.settings import CLIParameters, SettingsWrapper
from utils.pidfile import PidFile


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("TESTBED_CONFIG", type=str, help="Path to testbed package")
    parser.add_argument("--clean", action="store_true", required=False, default=False,
                        help="Clean network interfaces before startup (Beware of concurrent testbeds!)")
    parser.add_argument("--pause", choices=["SETUP", "INIT", "EXPERIMENT", "DISABLE"], 
                        required=False, default="DISABLE", type=str,
                        help="Stop after step of controller and wait (--wait)")
    parser.add_argument("-v", "--verbose", action="store_true", required=False, default=False,
                        help="Print TRACE log messages")
    parser.add_argument("-q", "--quiet", action="store_true", required=False, default=False,
                        help="Only print INFO, ERROR, SUCCESS or CRITICAL log messages")
    parser.add_argument("--wait", required=False, type=int, default=-1, 
                        help="Wait before shutdown, -1 = wait forever (default), x >= 0 = wait x seconds")
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

    if args.quiet:
        logger.remove()
        logger.add(sys.stdout, level="INFO")
    elif args.verbose:
        logger.remove()
        logger.add(sys.stdout, level="TRACE")
    
    parameters = CLIParameters()
    if os.path.isabs(args.TESTBED_CONFIG):
        parameters.config = args.TESTBED_CONFIG
    else:
        parameters.config = f"{os.getcwd()}/{args.TESTBED_CONFIG}"

    parameters.pause = args.pause
    parameters.wait = args.wait
    parameters.sudo_mode = args.sudo
    parameters.disable_kvm = args.no_kvm
    parameters.clean = args.clean
    parameters.experiment = args.experiment
    parameters.dont_use_influx = args.dont_store
    parameters.influx_path = args.influxdb
    parameters.skip_integration = args.skip_integration
    parameters.skip_substitution = args.skip_substitution

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

    SettingsWrapper.cli_paramaters = parameters

    if not args.sudo and os.geteuid() != 0:
        logger.critical("Unable to start: You need to be root!")
        sys.exit(1)


    script_name = sys.argv[0]
    try:
        with PidFile("/tmp/proto-testbed.pid", name=script_name):

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
            finally:
                controller.dismantle()
    except Exception as ex:
        logger.opt(exception=ex).critical(f"Another instance of '{script_name}' is still running.")
        sys.exit(1)

    if status:
        logger.success("Testbed was dismantled!")
        sys.exit(0)
    else:
        logger.critical("Testbed was dismantled after error.")
        sys.exit(1)
