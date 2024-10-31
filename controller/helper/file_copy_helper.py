from pathlib import Path
from typing import Tuple, Dict

from common.instance_manager_message import CopyFileMessageUpstream

class FileCopyAction():
    def __init__(self, source: Path, destination: Path, copy_to_instance: bool):
        self.source = source
        self.destination = destination
        self.copy_to_instance = copy_to_instance

class FileCopyHelper():
    def __init__(self, machine):
        self.machine = machine
        self.pending: Dict[str, FileCopyAction] = {}

    def copy(self, source_path: Path, destination_path: Path, copy_to_instance: bool) -> Tuple[bool, str]:
        return False, "Not implemented"

    def feedback_from_instance(proc_id: str):
        pass
