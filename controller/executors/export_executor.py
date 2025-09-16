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

from loguru import logger

from executors.base_executor import BaseExecutor
from utils.state_provider import TestbedStateProvider


class ExportExecutor(BaseExecutor):
    SUBCOMMAND = "export"
    ALIASES = ["e"]
    HELP = "Export results from a testbed execution"

    def __init__(self, subparser: argparse._SubParsersAction):
        super().__init__(subparser)
        self.subparser.add_argument("TYPE", choices=["image", "csv"], type=str, 
                                    help="File format for export")
        self.subparser.add_argument("TESTBED_CONFIG", type=str, help="Path to testbed package")
        self.subparser.add_argument("-ei", "--exclude-instance", required=False, 
                                    default=None, action="append",
                                    help="Dont export results from specific instance")
        self.subparser.add_argument("-ea", "--exclude-application", required=False, 
                                    default=None, action="append",
                                    help="Dont export results from specific applications")
        self.subparser.add_argument("-f", "--format", choices=["pdf", "svg", "png", "jpeg"],
                                    default="pdf", required=False, type=str,
                                    help="File export format for 'image' type")
        self.subparser.add_argument("-o", "--output", required=False, type=str, default="./out",
                                    help="Output path for exported result")
        self.subparser.add_argument("--skip_substitution", action="store_true", required=False, default=False, 
                                    help="Skip substitution of placeholders with environment variable values in config")

    def invoke(self, args, provider: TestbedStateProvider) -> int:
        from cli import CLI

        CLI(provider.log_verbose, None)

        if provider.experiment_generated:
            logger.critical(f"No experiment tag was specified, use -e to specify an experiment tag.")
            return 1

        from pathlib import Path
        testbed_config_path = Path(args.TESTBED_CONFIG)
        if not testbed_config_path.is_absolute():
            testbed_config_path = Path(os.getcwd()) / testbed_config_path

        from helper.export_helper import ResultExportHelper
        from utils.config_tools import load_config

        try:
            config_path = testbed_config_path / "testbed.json"
            testbed_config = load_config(config_path, args.skip_substitution)
        except Exception as ex:
            logger.opt(exception=ex).critical("Error loading testbed config")
            return 1

        try:
            exporter = ResultExportHelper(args.output, testbed_config, testbed_config_path, args.exclude_instance, args.exclude_application)
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to start data exporter")
            return 1

        try:
            match args.TYPE:
                case "image":
                    status = exporter.output_to_plot(args.output, args.format)
                case "csv":
                    status = exporter.output_to_flatfile(args.output)
                case _:
                    logger.critical(f"Unable to run export type '{args.TYPE}'")
                    return 1
            
            if not status:
                logger.critical("Unable to perform data export.")
                return 1
            else:
                logger.success("Data export completed.")
                return 0
        except Exception as ex:
            logger.opt(exception=ex).critical("Unhandled error during data export")
            return 1
