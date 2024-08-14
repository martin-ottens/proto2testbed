#!/usr/bin/python3

import argparse
import sys
import os

from loguru import logger

from controller import Controller
from utils.settings import CLIParameters, SettingsWrapper


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
    parser.add_argument("--sudo", "-s", action="store_true", required=False, default=False,
                        help="Prepend 'sudo' to all commands (non-interactive), root required otherwise")
    parser.add_argument("--experiment", "-e", required=False, default=None, type=str, 
                        help="Name of experiment series, auto generated if omitted")
    parser.add_argument("--dont_store", "-d", required=False, default=False, action="store_true", 
                        help="Dont store experiment results to InfluxDB on host")
    parser.add_argument("--influxdb", "-i", required=False, default=None, type=str, 
                        help="Path to InfluxDB config, use defaults/environment if omitted")
    
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
    parameters.clean = args.clean
    parameters.experiment = args.experiment
    parameters.dont_use_influx = args.dont_store
    parameters.influx_path = args.influxdb

    SettingsWrapper.cli_paramaters = parameters

    if not args.sudo and os.geteuid() != 0:
        logger.critical("Unable to start: You need to be root!")
        sys.exit(1)

    controller = Controller()
    status = controller.main()
    controller.dismantle()

    if status:
        logger.success("Testbed was dismantled!")
        sys.exit(0)
    else:
        logger.critical("Testbed was dismantled after error.")
        sys.exit(1)
