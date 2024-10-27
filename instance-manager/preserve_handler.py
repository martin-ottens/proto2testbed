import subprocess
import shutil
import os

from typing import List
from pathlib import Path

from management_client import ManagementClient, DownstreamMassage
from common.instance_manager_message import InstanceStatus

class PreserveHandler():
    def __init__(self, manager: ManagementClient, exchange_mount: str, exchange_p9_dev: str):
        self.manager = manager
        self.exchange_mount = exchange_mount
        self.exchange_p9_dev = exchange_p9_dev
        self.is_mounted = False
        self.files: List[str] = []
        pass

    def batch_add(self, preserve_files: List[str]):
        self.files.extend(preserve_files)

    def add(self, preserve_file: str):
        self.files.append(preserve_file)

    def preserve(self) -> bool:
        if len(self.files) == 0:
            return True

        if not self.is_mounted:
            proc = None
            try:
                proc = subprocess.run(["mount", "-t", "9p", "-o", "trans=virtio", self.exchange_p9_dev, self.exchange_mount])
            except Exception as ex:
                message = DownstreamMassage(InstanceStatus.FAILED, f"Unable to mount exchange direcory!")
                self.manager.send_to_server(message)
                raise Exception("Unable to mount exchange directory!") from ex

            if proc is not None and proc.returncode != 0:
                message = DownstreamMassage(InstanceStatus.FAILED, 
                                            f"Mounting of exchange directory failed with code ({proc.returncode})\nSTDOUT: {proc.stdout.decode('utf-8')}\nSTDERR: {proc.stderr.decode('utf-8')}")
                self.manager.send_to_server(message)
                raise Exception(f"Unable to mount exchange directory: {proc.stderr}")
            
            self.is_mounted = True

        for preserve_file in message.preserve_files:
            path = Path(preserve_file)
            if not path.is_absolute():
                message = DownstreamMassage(InstanceStatus.MSG_ERROR, 
                                            f"Unable to preserve '{preserve_file}': Not an absolute path")
                self.manager.send_to_server(message)
                continue

            if preserve_file.startswith(self.exchange_mount):
                continue

            if not path.exists():
                message = DownstreamMassage(InstanceStatus.MSG_ERROR, 
                                            f"Unable to preserve '{preserve_file}': Path does not exists")
                self.manager.send_to_server(message)
                continue

            destination_path = os.path.join(self.exchange_mount, preserve_file.lstrip('/'))
            shutil.copytree(path, destination_path)
        
        return True
