import argparse

from executors.base_executor import BaseExecutor

class CleanExecutor(BaseExecutor):
    SUBCOMMAND = "clean"
    ALIASES = ["c"]
    HELP = "Clean dangling testbed parts (files, interfaces etc.)"

    def __init__(self, subparser: argparse._SubParsersAction):
        super().__init__(subparser)
        self.subparser.add_argument("-a", "--all", required=False, default=False, action="store_true",
                                    help="Also clean testbeds from different users")

    def invoke(self, args) -> int:
        from utils.cleanup import delete_residual_parts
        return delete_residual_parts()
    
    def requires_priviledges(self) -> bool:
        return True
