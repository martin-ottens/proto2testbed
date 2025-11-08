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

import random
import string
import shutil
import os

from pathlib import Path
from typing import Tuple, Dict
from loguru import logger

from common.instance_manager_message import CopyFileMessageUpstream
from utils.system_commands import copy_file_or_directory, remove_file_or_directory, rename_file_or_directory


class FileCopyAction:
    def __init__(self, source: Path, destination: Path, copy_to_instance: bool):
        self.source = source
        self.destination = destination
        self.copy_to_instance = copy_to_instance


class FileCopyHelper:
    def __init__(self, instance, executor: str):
        self.instance = instance
        self.executor = executor
        self.pending: Dict[str, FileCopyAction] = {}

    def copy(self, source_path: Path, destination_path: Path, copy_to_instance: bool) -> Tuple[bool, str]:
        proc_id: str = ''.join(random.choices(string.ascii_letters, k=10))

        if copy_to_instance:
            if not source_path.exists():
                return False, f"Source path '{source_path}' does not exist."
            
            # Copy files from source path to exchange mount
            target_on_mount = self.instance.get_p9_data_path()
            if target_on_mount is None:
                return False, "Exchange mount for selected Instance not available."
            
            target = target_on_mount / Path(proc_id)
            
            if not copy_file_or_directory(source_path, target, self.executor):
                return False, f"Copy to {target} failed."
            
            # Instruct the Instance to copy from exchange mount to target
            action = FileCopyAction(source_path, destination_path, copy_to_instance)
            self.pending[proc_id] = action

            message = CopyFileMessageUpstream(proc_id, 
                                              str(destination_path), 
                                              os.path.basename(str(source_path)), 
                                              proc_id)
            self.instance.send_message(message)
        
            # (Wait for reply)
            return True, "Waiting for Instance to complete the copy process."
        else:
            action = FileCopyAction(source_path, destination_path, copy_to_instance)
            self.pending[proc_id] = action

            # Instruct the Instance to copy from source to exchange mount
            message = CopyFileMessageUpstream(str(source_path), proc_id, None, proc_id)
            self.instance.send_message(message)

            # (Copy from exchange mount to target)
            return True, "Waiting for Instance to start the copy process."

    def feedback_from_instance(self, proc_id: str):
        action = self.pending.pop(proc_id, None)
        if action is None:
            logger.error(f"Unknown Copy-Process-ID: {proc_id}")
        
        if action.copy_to_instance:
            # All is done, just print a message.
            logger.info(f"Successfully copied from '{action.source}' to '{self.instance.name}:{action.destination}'")
            del action
        else:
            # File is in exchange mount, copy it to our file system
            source_on_mount = self.instance.get_p9_data_path()
            if source_on_mount is None:
                logger.error(f"Error while performing copy: Exchange mount for Instance '{self.instance.name}' not available.")
                del action
                return
            
            source: Path = source_on_mount / Path(proc_id)

            if not source.exists():
                logger.error(f"Error while performing copy: Source '{source}' does not exist.")
                del action
                return

            success = True
            if not copy_file_or_directory(source, action.destination, self.executor):
                logger.error(f"Error while copying '{source}' to '{action.destination}'")
                success = False
            
            if not remove_file_or_directory(source):
                logger.error(f"Unable to clean up '{source}' after successful copy!")
                success = False

            if action.destination.is_dir():
                rename_path = action.destination / Path(os.path.basename(source))
                rename_to = action.destination / Path(os.path.basename(action.source))

                if not rename_file_or_directory(rename_path, str(rename_to)):
                    logger.error(f"Unable to rename '{rename_path}' to '{rename_to}' after successful copy!")
                    success = False

            if success:
                logger.info(f"Successfully copied from '{self.instance.name}:{action.source}' to '{action.destination}'")

            del action

    def clean_mount(self):
        on_mount = self.instance.get_p9_data_path()
        if on_mount is None:
            return

        for proc_id, _ in self.pending.items():
            logger.warning(f"Copy '{proc_id}' for Instance '{self.instance.name}' is still pending.")
            to_delete: Path = on_mount / Path(proc_id)
            try:
                if to_delete.exists:
                    shutil.rmtree(to_delete, ignore_errors=True)
            except Exception as ex:
                logger.opt(exception=ex).warning(f"Unable to delete pending copy for '{self.instance.name}' with ID '{proc_id}'")
