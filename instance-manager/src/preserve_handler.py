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

import subprocess
import shutil
import os
import sys

from typing import List
from pathlib import Path

from management_client import ManagementClient, DownstreamMessage
from common.instance_manager_message import InstanceMessageType, LogMessageType
from global_state import GlobalState


class PreserveHandler:
    def __init__(self, manager: ManagementClient, exchange_p9_dev: str):
        self.manager = manager
        self.exchange_mount = GlobalState.exchange_mount_path
        self.exchange_p9_dev = exchange_p9_dev
        self.files: List[str] = []
        pass

    def batch_add(self, preserve_files: List[str]):
        if preserve_files is not None:
            self.files.extend(preserve_files)

    def add(self, preserve_file: str):
        if preserve_file is not None:
            self.files.append(preserve_file)

    def check_and_add_exchange_mount(self):
        if os.path.ismount(self.exchange_mount):
            return

        proc = None
        try:
            proc = subprocess.run(["mount", "-t", "9p", "-o", "trans=virtio", self.exchange_p9_dev, self.exchange_mount])
        except Exception as ex:
            message = DownstreamMessage(InstanceMessageType.FAILED, f"Unable to mount exchange directory!")
            self.manager.send_to_server(message)
            raise Exception("Unable to mount exchange directory!") from ex

        if proc.stdout is not None:
            self.manager.send_extended_system_log(type=LogMessageType.STDOUT, message=proc.stdout.decode('utf-8'), print_to_user=False)
        if proc.stderr is not None:
            self.manager.send_extended_system_log(type=LogMessageType.STDERR, message=proc.stderr.decode('utf-8'), print_to_user=False)
        
        if proc is not None and proc.returncode != 0:
            message = DownstreamMessage(InstanceMessageType.FAILED, 
                                        f"Mounting of exchange directory failed with code ({proc.returncode})")
            self.manager.send_to_server(message)
            raise Exception(f"Unable to mount exchange directory: {proc.stderr.decode('utf-8')}")

    def preserve(self) -> bool:
        if len(self.files) == 0:
            return True

        self.check_and_add_exchange_mount()

        for preserve_file in self.files:
            print(f"Preserving file or directory '{preserve_file}'", file=sys.stderr, flush=True)
            try:
                path = Path(preserve_file)
                if not path.is_absolute():
                    print(f"Preservation of '{preserve_file}' failed: No absolute path.", file=sys.stderr, flush=True)
                    self.manager.send_extended_system_log(type=LogMessageType.MSG_ERROR,
                                                          message=f"Unable to preserve '{preserve_file}': Not an absolute path",
                                                          print_to_user=True)
                    continue

                if preserve_file.startswith(self.exchange_mount):
                    continue

                if not path.exists():
                    print(f"Preservation of '{preserve_file}' failed: Path does not exists.", file=sys.stderr, flush=True)
                    self.manager.send_extended_system_log(type=LogMessageType.MSG_ERROR,
                                                          message=f"Unable to preserve '{preserve_file}': Path does not exists",
                                                          print_to_user=True)
                    continue

                destination_path = os.path.join(self.exchange_mount, preserve_file.lstrip('/'))
                if path.is_dir():
                    shutil.copytree(path, destination_path)
                else:
                    os.makedirs(os.path.dirname(destination_path), exist_ok=True)
                    shutil.copy2(path, destination_path)
            except Exception as ex:
                print(f"Preservation of '{preserve_file}' failed: Unhandled error: {ex}", file=sys.stderr, flush=True)
                self.manager.send_extended_system_log(type=LogMessageType.MSG_ERROR,
                                                      message=f"Unable to preserve '{preserve_file}': Unhandled error: {ex}",
                                                      print_to_user=True)
                print(f"Error during preservation of '{preserve_file}': {ex}", flush=True, file=sys.stderr)
        
        return True
