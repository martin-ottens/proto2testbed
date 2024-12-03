#!/usr/bin/python3

import argparse
import sys
import os
import signal
import random
import string
import importlib.util
import inspect

from loguru import logger
from pathlib import Path

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
            except Exception as ex:
                logger.opt(exception=ex).critical(f"Error loading command executor file '{filename}'")
                sys.exit(1)

    args = parser.parse_args()

    # Some lazy loading from there for better CLI reactivity
    from cli import CLI
    from utils.settings import CommonSetings
    import psutil

    CLI.setup_early_logging()

    original_uid = os.environ.get("SUDO_UID", None)
    if original_uid is None:
        original_uid = os.getuid()

    CommonSetings.experiment = args.experiment
    if CommonSetings.experiment is None:
        CommonSetings.experiment = "".join(random.choices(string.ascii_letters + string.digits, k=8))
        CommonSetings.experiment_generated = True

    CommonSetings.executor = original_uid
    CommonSetings.main_pid = os.getpid()
    CommonSetings.cmdline = " ".join(psutil.Process(CommonSetings.main_pid).cmdline())
    CommonSetings.unique_run_name = f"{''.join(CommonSetings.experiment.split())}-{str(original_uid)}-{args.mode}"
    CommonSetings.app_base_path = app_base_path
    CommonSetings.log_verbose = args.verbose
    CommonSetings.sudo_mode = args.sudo
    CommonSetings.influx_path = args.influxdb

    from utils.config_tools import DefaultConfigs
    CommonSetings.default_configs = DefaultConfigs("/etc/proto2testbed/proto2testbed_defaults.json")

    executor: BaseExecutor = subcommands.get(args.mode, None)
    if executor is None:
        logger.critical(f"Unable to get implementation for subcommand '{args.mode}'")
        sys.exit(1)

    if executor.requires_priviledges():
        if not CommonSetings.sudo_mode and os.geteuid() != 0:
            logger.critical("Unable to start: You need to be root!")
            sys.exit(1)

    
    try:
        sys.exit(executor.invoke(args))
    except Exception as ex:
        logger.opt(exception=ex).critical(f"Error calling invoke of subcommand '{args.mode}'")
        sys.exit(1)


if __name__ == "__main__":
    main()
