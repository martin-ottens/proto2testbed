#!/usr/bin/python3
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
import sys
import os
import random
import string
import importlib.util
import inspect

from loguru import logger
from pathlib import Path
from typing import Dict

from executors.base_executor import BaseExecutor

def main():
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
    
    app_base_path = Path(__file__).parent.resolve()
    subcommands = {}
    aliases: Dict[str, str] = {}

    executors_base_path = app_base_path / "executors"
    for filename in os.listdir(executors_base_path):
        if filename.endswith(".py") and filename not in ("__init__.py", "base_executor.py"):
            try:
                module_name = filename[:-3] # Skip .py
                filepath = Path(os.path.join(executors_base_path, filename)).absolute()
                spec = importlib.util.spec_from_file_location(module_name, filepath)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if not issubclass(obj, BaseExecutor) or obj is BaseExecutor:
                        continue

                    if obj.SUBCOMMAND == BaseExecutor.SUBCOMMAND:
                        continue

                    subcommand_parser = subparsers.add_parser(obj.SUBCOMMAND, 
                                                                aliases=obj.ALIASES,
                                                                help=obj.HELP,
                                                                parents=[common_parser])
                    subcommands[obj.SUBCOMMAND] = obj(subcommand_parser)

                    for alias in obj.ALIASES:
                        aliases[alias] = obj.SUBCOMMAND

            except Exception as ex:
                logger.opt(exception=ex).critical(f"Error loading command executor file '{filename}'")
                sys.exit(1)

    args = parser.parse_args()

    # Some lazy loading from there for better CLI reactivity
    from cli import CLI
    from utils.settings import CommonSettings
    import psutil

    CLI.setup_early_logging()

    original_uid = os.environ.get("SUDO_UID", None)
    if original_uid is None:
        original_uid = os.getuid()

    CommonSettings.experiment = args.experiment
    if CommonSettings.experiment is None:
        CommonSettings.experiment = "".join(random.choices(string.ascii_letters + string.digits, k=8))
        CommonSettings.experiment_generated = True

    CommonSettings.executor = int(original_uid)
    CommonSettings.main_pid = os.getpid()
    CommonSettings.cmdline = " ".join(psutil.Process(CommonSettings.main_pid).cmdline())
    CommonSettings.unique_run_name = f"{''.join(CommonSettings.experiment.split())}-{str(original_uid)}-{args.mode}"
    CommonSettings.app_base_path = app_base_path
    CommonSettings.log_verbose = args.verbose
    CommonSettings.sudo_mode = args.sudo
    CommonSettings.influx_path = args.influxdb

    from utils.config_tools import DefaultConfigs
    CommonSettings.default_configs = DefaultConfigs("/etc/proto2testbed/proto2testbed_defaults.json")

    mode = args.mode
    if mode in aliases.keys():
        mode = aliases.get(mode)
    executor: BaseExecutor = subcommands.get(mode, None)

    if executor is None:
        logger.critical(f"Unable to get implementation for subcommand '{mode}'")
        sys.exit(1)

    if executor.requires_priviledges():
        if not CommonSettings.sudo_mode and os.geteuid() != 0:
            logger.critical("Unable to start: You need to be root!")
            sys.exit(1)

    try:
        sys.exit(executor.invoke(args))
    except Exception as ex:
        logger.opt(exception=ex).critical(f"Error calling invoke of subcommand '{mode}'")
        sys.exit(1)


if __name__ == "__main__":
    main()
