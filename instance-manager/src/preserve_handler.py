import subprocess
import shutil
import os
import sys

from typing import List
from pathlib import Path

from management_client import ManagementClient, DownstreamMassage
from common.instance_manager_message import InstanceStatus

class PreserveHandler():
    def __init__(self, manager: ManagementClient, exchange_mount: str, exchange_p9_dev: str):
        self.manager = manager
        self.exchange_mount = exchange_mount
        self.exchange_p9_dev = exchange_p9_dev
        self.files: List[str] = []
        pass

    def batch_add(self, preserve_files: List[str]):
        if preserve_files is not None:
            self.files.extend(preserve_files)

    def add(self, preserve_file: str):
        if preserve_file is not None:
            self.files.append(preserve_file)

    def preserve(self) -> bool:
        if len(self.files) == 0:
            return True

        if not os.path.ismount(self.exchange_mount):
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

        for preserve_file in self.files:
            print(f"Preserving file or direcory '{preserve_file}'", file=sys.stderr, flush=True)
            try:
                path = Path(preserve_file)
                if not path.is_absolute():
                    print(f"Preservation of '{preserve_file}' failed: No absolute path.", file=sys.stderr, flush=True)
                    message = DownstreamMassage(InstanceStatus.MSG_ERROR, 
                                                f"Unable to preserve '{preserve_file}': Not an absolute path")
                    self.manager.send_to_server(message)
                    continue

                if preserve_file.startswith(self.exchange_mount):
                    continue

                if not path.exists():
                    print(f"Preservation of '{preserve_file}' failed: Path does not exists.", file=sys.stderr, flush=True)
                    message = DownstreamMassage(InstanceStatus.MSG_ERROR, 
                                                f"Unable to preserve '{preserve_file}': Path does not exists")
                    self.manager.send_to_server(message)
                    continue

                destination_path = os.path.join(self.exchange_mount, preserve_file.lstrip('/'))
                if path.is_dir():
                    shutil.copytree(path, destination_path)
                else:
                    os.makedirs(os.path.dirname(destination_path), exist_ok=True)
                    shutil.copy2(path, destination_path)
            except Exception as ex:
                print(f"Preservation of '{preserve_file}' failed: Unhandled error: {ex}", file=sys.stderr, flush=True)
                message = DownstreamMassage(InstanceStatus.MSG_ERROR, 
                                                f"Unable to preserve '{preserve_file}': Unhandeled error: {ex}")
                print(f"Error during preservation of '{preserve_file}': {ex}", flush=True, file=sys.stderr)
        
        return True
