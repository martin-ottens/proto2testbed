import argparse

from abc import ABC, abstractmethod

class BaseExecutor(ABC):
    SUBCOMMAND = "##DONT_LOAD##"
    ALIASES = []
    HELP = "I'm an abstract base class"

    def __init__(self, subparser: argparse._SubParsersAction):
        self.subparser = subparser

    @abstractmethod
    def invoke(self, args) -> int:
        pass

    def requires_priviledges(self) -> bool:
        return False
