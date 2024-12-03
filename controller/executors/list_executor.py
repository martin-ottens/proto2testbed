import argparse

from executors.base_executor import BaseExecutor

class ListExecutor(BaseExecutor):
    SUBCOMMAND = "list"
    ALIASES = ["ls"]
    HELP = "List all running testbeds an their instances"

    def __init__(self, subparser: argparse._SubParsersAction):
        super().__init__(subparser)
        self.subparser.add_argument("-a", "--all", required=False, default=False, action="store_true",
                                    help="Show testbeds from all users")

    def invoke(self, args) -> int:
        pass
