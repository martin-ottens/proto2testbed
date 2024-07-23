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
    parser.add_argument("--wait", required=False, type=int, default=0, 
                        help="Wait before shutdown, 0 = package value, -1 = wait forever, x > 0 = wait x seconds")
    parser.add_argument("--sudo", "-s", action="store_true", required=False, default=False,
                        help="Prepend 'sudo' to all commands (non-interactive), root required otherwise")
    
    args = parser.parse_args()

    if args.quiet:
        logger.remove()
        logger.add(sys.stdout, level="INFO")
    elif args.verbose:
        logger.remove()
        logger.add(sys.stdout, level="TRACE")
    
    parameters = CLIParameters()
    parameters.config = args.TESTBED_CONFIG
    parameters.pause = args.pause
    parameters.wait = args.wait
    parameters.sudo_mode = args.sudo
    parameters.clean = args.clean

    SettingsWrapper.cli_paramaters = parameters

    if not args.sudo and os.geteuid() != 0:
        logger.critical("Unable to start: You need to be root!")
        sys.exit(1)

    Controller().main()
