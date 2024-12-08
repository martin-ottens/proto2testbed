import argparse

from loguru import logger

from executors.base_executor import BaseExecutor
from utils.settings import CommonSettings

class ExportExecutor(BaseExecutor):
    SUBCOMMAND = "export"
    ALIASES = ["e"]
    HELP = "Export results from a testbed execution"

    def __init__(self, subparser: argparse._SubParsersAction):
        super().__init__(subparser)

    def invoke(self, args) -> int:
        pass

        # check for expierment_generated