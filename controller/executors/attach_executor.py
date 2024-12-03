import argparse

from executors.base_executor import BaseExecutor

class AttachExecutor(BaseExecutor):
    SUBCOMMAND = "attach"
    ALIASES = ["a"]
    HELP = "Attach to an Instance"

    def __init__(self, subparser: argparse._SubParsersAction):
        super().__init__(subparser)
        self.subparser.add_argument("-s", "--ssh", required=False, default=False, action="store_true",
                                    help="Use SSH instead of serial connection (if available)")

    def invoke(self, args) -> int:
        pass
