import random
import string
import shutil

from pathlib import Path
from typing import Tuple, Dict
from loguru import logger

from common.instance_manager_message import CopyFileMessageUpstream
from utils.system_commands import copy_file_or_directory, remove_file_or_direcory

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
        proc_id: str = ''.join(random.choices(string.ascii_letters, k=10))

        if copy_to_instance:
            if not source_path.exists():
                return False, f"Source path '{source_path}' does not exist."
            
            # Copy files from source path to exchange mount
            target_on_mount = self.machine.get_p9_data_path()
            if target_on_mount is None:
                return False, "Exchange mount for selected Instance not available."
            
            target = target_on_mount / Path(proc_id)
            
            if not copy_file_or_directory(source_path, target):
                return False, f"Copy to {target} failed."
            
            # Instruct the Instance to copy from exchange mount to target
            action = FileCopyAction(source_path, destination_path, copy_to_instance)
            self.pending[proc_id] = action

            message = CopyFileMessageUpstream(proc_id, str(destination_path), proc_id)
            self.machine.send_message(message.to_json().encode("utf-8"))
        
            # (Wait for reply)
            return True, "Waiting for Instance to complete the copy process."
        else:
            action = FileCopyAction(source_path, destination_path, copy_to_instance)
            self.pending[proc_id] = action

            # Instruct the Instance to copy from source to exchange mount
            message = CopyFileMessageUpstream(str(source_path), proc_id, proc_id)
            self.machine.send_message(message.to_json().encode("utf-8"))

            # (Copy from exchange mount to target)
            return True, "Waiting for Instance to start the copy process."

    def feedback_from_instance(self, proc_id: str):
        action = self.pending.pop(proc_id, None)
        if action is None:
            logger.error(f"Unknown Copy-Process-ID: {proc_id}")
        
        if action.copy_to_instance:
            # All is done, just print a message.
            logger.info(f"Sucessfully copied from '{action.source}' to '{self.machine.name}:{action.destination}'")
            del action
        else:
            # File is in exchange mount, copy it to our file system
            source_on_mount = self.machine.get_p9_data_path()
            if source_on_mount is None:
                logger.error(f"Error while performing copy: Exchange mount for Instance '{self.machine.name}' not available.")
                del action
                return
            
            source: Path = source_on_mount / Path(proc_id)

            if not source.exists():
                logger.error(f"Error while performing copy: Source '{source}' does not exist.")
                del action
                return

            success = True
            if not copy_file_or_directory(source, action.destination):
                logger.error(f"Error while copying '{source}' to '{action.destination}'")
                success = False
            
            if not remove_file_or_direcory(source):
                logger.error(f"Unable to clean up '{source}' after sucesful copy!")
                success = False

            if success:
                logger.info(f"Sucessfully copied from '{self.machine.name}:{action.source}' to '{action.destination}'")

            del action

    def clean_mount(self):
        on_mount = self.machine.get_p9_data_path()
        if on_mount is None:
            return

        for proc_id, _ in self.pending.items():
            logger.warning(f"Copy '{proc_id}' for Instance '{self.machine.name}' is still pending.")
            to_delete: Path = on_mount / Path(proc_id)
            try:
                if to_delete.exists:
                    shutil.rmtree(to_delete, ignore_errors=True)
            except Exception as ex:
                logger.opt(exception=ex).warning(f"Unable to delete pending copy for '{self.machine.name}' with ID '{proc_id}'")
