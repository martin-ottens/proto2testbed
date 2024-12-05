import argparse

from loguru import logger

from executors.base_executor import BaseExecutor
from utils.settings import CommonSettings

class CleanExecutor(BaseExecutor):
    SUBCOMMAND = "clean"
    ALIASES = ["c"]
    HELP = "Clean results from a testbed execution"

    def __init__(self, subparser: argparse._SubParsersAction):
        super().__init__(subparser)

    def invoke(self, args) -> int:
        pass
