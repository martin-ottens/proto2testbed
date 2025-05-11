#!/usr/bin/python3
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
import os
import shutil
import sys

from pathlib import Path
from enum import Enum, auto
from typing import Optional

from preserve_handler import PreserveHandler
from management_daemon import IMDaemonServer
from management_client import ManagementClient, DownstreamMassage, get_hostname
from application_manager import ApplicationManager
from global_state import GlobalState

from common.instance_manager_message import *


FILE_SERVER_PORT = 4242
STATE_FILE = "/tmp/im-setup-succeeded"
TESTBED_PACKAGE_MOUNT = "/opt/testbed"
TESTBED_PACKAGE_P9_DEV = "tbp"
EXCHANGE_MOUNT = "/mnt"
EXCHANGE_P9_DEV = "exchange"
IM_SOCKET_PATH = "/tmp/im.sock"


class IMState(Enum):
    STARTED = auto()
    INITIALIZED = auto()
    APPS_READY = auto()
    EXPERIMENT_RUNNING = auto()
    READY_FOR_SHUTDOWN = auto()
    FAILED = auto()


class InstanceManager:
    
    def __init__(self):
        self.instance_name = get_hostname()
        self.manager = ManagementClient(self.instance_name)
        self.preserver = PreserveHandler(self.manager, EXCHANGE_P9_DEV)
        self.daemon = IMDaemonServer(self.manager, self.preserver)
        self.state = IMState.STARTED
        self.application_manager: Optional[ApplicationManager] = None

    def message_to_controller(self, message_type: InstanceMessageType, payload = None):
        self.manager.send_to_server(DownstreamMassage(message_type, payload))

    def handle_initialize(self, data) -> bool:
        # 1. Check initialization data from management server
        if "script" not in data or "environment" not in data:
            raise Exception("Initialization message error: Fields are missing")

        if not isinstance(data.get("environment"), dict):
            raise Exception("Initialization message error: Environment should be a dict")

        print(f"Got 'initialize' instructions from Management Server", file=sys.stderr, flush=True)

        data["environment"]["TESTBED_PACKAGE"] = GlobalState.testbed_package_path

        init_message = InitializeMessageUpstream(**data)

        # 2. Mount the testbed package from host via virtio p9 (if not already done)
        if not os.path.ismount(GlobalState.testbed_package_path):
            os.mkdir(GlobalState.testbed_package_path, mode=0o777)
            proc = None
            try:
                proc = subprocess.run(["mount", "-t", "9p", "-o", "trans=virtio", TESTBED_PACKAGE_P9_DEV, GlobalState.testbed_package_path])
            except Exception as ex:
                self.message_to_controller(InstanceMessageType.FAILED, f"Unable to mount testbed package: {ex}")
                return False

            if proc is not None and proc.returncode != 0:
                self.message_to_controller(InstanceMessageType.FAILED, 
                                                        f"Mounting of testbed package failed with code ({proc.returncode})\nSTDOUT: {proc.stdout.decode('utf-8')}\nSTDERR: {proc.stderr.decode('utf-8')}")
                print(f"Testbed Package mounted to {TESTBED_PACKAGE_P9_DEV}", file=sys.stderr, flush=True)
                return False

        # 3. Execute the setup script from mounted testbed package
        if init_message.script is not None:
            print(f"Running setup script {init_message.script}", file=sys.stderr, flush=True)
            os.chdir(GlobalState.testbed_package_path)

            if init_message.environment is not None:
                for key, value in init_message.environment.items():
                    os.environ[key] = value

                proc = None
                try:
                    proc = subprocess.run(["/bin/bash", init_message.script], capture_output=True, shell=False)
                except Exception as ex:
                    self.message_to_controller(InstanceMessageType.FAILED, f"Setup script failed:\nMESSAGE: {ex}")
                    print(f"Unable to run setup_script: {ex}", file=sys.stderr, flush=True)
                    return False

                if proc is not None and proc.returncode != 0:
                    self.message_to_controller(InstanceMessageType.FAILED, 
                                                    f"Setup script failed ({proc.returncode})\nSTDOUT: {proc.stdout.decode('utf-8')}\nSTDERR: {proc.stderr.decode('utf-8')}")
                    print(f"Unable to run setup_script': {proc.stderr.decode('utf-8')}", file=sys.stderr, flush=True)
                    return False
                
                print(f"Execution of setup script {init_message.script} completed", file=sys.stderr, flush=True)
            else:
                print(f"No setup script in 'initialize' message, skipping setup.", file=sys.stderr, flush=True)

        # 4. Report status to management server
        Path(STATE_FILE).touch()
        self.message_to_controller(InstanceMessageType.INITIALIZED)
        return True

    def install_apps(self, data) -> bool:
        print(f"Starting installation of Applications", file=sys.stderr, flush=True)
        applications = InstallApplicationsMessageUpstream.from_json(data)

        if self.application_manager is not None:
            print(f"Purging previous installed application_manager")
            del self.application_manager
        
        self.application_manager = ApplicationManager(self, self.manager, self.instance_name)

        return self.application_manager.install_apps(applications.applications)

    def run_apps(self) -> bool:
        if self.application_manager is None:
            print("Unable to run experiment: No application manager is installed")
            self.message_to_controller(InstanceMessageType.MSG_ERROR, 
                                   f"Can' run apps: No applications manager is configured.")
            return False
        
        return self.application_manager.run_apps()

    def handle_finish(self, data) -> False:
        print(f"Starting File Preservation", file=sys.stderr, flush=True)
        finish_message = FinishInstanceMessageUpstream(**data)

        if not finish_message.do_preserve:
            print(f"Skipping preservation, it is not enabled in the controller", file=sys.stderr, flush=True)
            self.message_to_controller(InstanceMessageType.FINISHED)
            return True

        self.preserver.batch_add(finish_message.preserve_files)
        
        if self.preserver.preserve():
            self.message_to_controller(InstanceMessageType.FINISHED)
            print(f"File preservation completed, Instance ready for shut down", file=sys.stderr, flush=True)
            return True
        else:
            self.message_to_controller(InstanceMessageType.FAILED, "File preservation failed")
            print(f"File preservation failed.", file=sys.stderr, flush=True)
            return False
        
    def handle_file_copy(self, data) -> bool:
        copy_instructions = CopyFileMessageUpstream(**data)

        if copy_instructions.proc_id is None:
            self.message_to_controller(InstanceMessageType.MSG_ERROR, 
                                       f"Copy failed, no proc_id was provided to Instance.")
            print(f"Invalid copy instruction packet: proc_id missing!")
            return True

        source = Path(copy_instructions.source)
        target = Path(copy_instructions.target)
        source_is_local = False
        if source.is_absolute():
            source_is_local = True

        if target.is_absolute() and source_is_local:
            self.message_to_controller(InstanceMessageType.MSG_ERROR, 
                                       f"Can't copy from '{copy_instructions.source}' to '{copy_instructions.target}': Both are local.")
            print(f"Unable to process CopyFileMessage: Cannot copy from local to local", file=sys.stderr, flush=True)
            return True
        
        self.preserver.check_and_add_exchange_mount()
        
        if not source_is_local:
            source = Path(EXCHANGE_MOUNT) / source
        else:
            target = Path(EXCHANGE_MOUNT) / target

        if not source.exists():
            self.message_to_controller(InstanceMessageType.MSG_ERROR, 
                                   f"Can't copy from '{source}': File or directory does not exist!")
            print(f"Unable to process CopyFileMessage: File or directory '{source}' does not exist!", file=sys.stderr, flush=True)
            return True

        try:
            destination = target
            if target.is_dir():
                destination = target / Path(os.path.basename(source))

            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                shutil.copy2(source, destination)

            if not source_is_local:
                if source.is_dir():
                    shutil.rmtree(source, ignore_errors=True)
                else:
                    os.remove(source)

            if copy_instructions.source_renameto is not None:
                rename_path = target / Path(os.path.basename(source))
                rename_to = target / copy_instructions.source_renameto

                os.rename(rename_path, rename_to)
        
        except Exception as ex:
            self.message_to_controller(InstanceMessageType.MSG_ERROR, 
                                   f"Copy failed on Instance: {ex}")
            print(f"Unable to copy from '{source}' to '{target}': {ex}", file=sys.stderr, flush=True)
            return True

        self.message_to_controller(InstanceMessageType.MSG_DEBUG, 
                                   f"Copied from to '{source}' to '{target}' on Instance.")
        print(f"Copied from to '{source}' to '{target}'", file=sys.stderr, flush=True)
        message = DownstreamMassage(InstanceMessageType.COPIED_FILE, copy_instructions.proc_id)
        self.manager.send_to_server(message)
        return True

    def _run_instance_manager(self):
        self.manager.start()
        self.daemon.start()

        self.message_to_controller(InstanceMessageType.STARTED)

        # Already initialized, let the controller know
        if Path(STATE_FILE).is_file():
            self.state = IMState.INITIALIZED
            self.message_to_controller(InstanceMessageType.INITIALIZED)
        
        while True:
            data = self.manager.wait_for_command()

            if "status" not in data:
                raise Exception("Invalid message received from management server")

            match data.get("status"):
                case InitializeMessageUpstream.status_name:
                    if self.state != IMState.STARTED:
                        print(f"Got 'initialize' message from controller, but im in state {self.state.value}, skipping init.")
                        self.message_to_controller(InstanceMessageType.INITIALIZED)
                    else:
                        if self.handle_initialize(data):
                            self.state = IMState.INITIALIZED
                        else:
                            self.state = IMState.FAILED
                case InstallApplicationsMessageUpstream.status_name:
                    if self.state != IMState.INITIALIZED and self.state != IMState.APPS_READY:
                        print(f"Got 'install_apps' message from controller, but im in state {self.state.value}, skipping.")
                        self.message_to_controller(InstanceMessageType.MSG_ERROR, "Instance is not ready for app installation.")
                    else:
                        self.install_apps(data)
                        self.state = IMState.APPS_READY
                case RunApplicationsMessageUpstream.status_name:
                    if self.state != IMState.APPS_READY:
                        print(f"Got 'run_apps' message from controller, but im in state {self.state.value}, skipping.")
                        self.message_to_controller(InstanceMessageType.MSG_ERROR, "Instance has not yet installed apps.")
                    else:
                        self.state = IMState.EXPERIMENT_RUNNING
                        if self.run_apps():
                            self.state = IMState.APPS_READY
                        else:
                            self.state = IMState.FAILED
                case CopyFileMessageUpstream.status_name:
                    if not self.handle_file_copy(data):
                        self.state = IMState.FAILED
                case FinishInstanceMessageUpstream.status_name:
                    if self.handle_finish(data):
                        self.state = IMState.READY_FOR_SHUTDOWN
                    else:
                        self.state = IMState.FAILED
                case _:
                    raise Exception(f"Invalid 'status' in message: {data.get('status')}")
            
            if self.state == IMState.FAILED:
                print("Instance Manager has entered FAILED state.")

    def run(self):
        try:
            self._run_instance_manager()
        except Exception as ex:
            raise ex
        finally:
            print(f"Instance Manager is shutting down", file=sys.stderr, flush=True)
            if self.daemon is not None:
                self.daemon.stop()
            if self.manager is not None:
                self.manager.stop()


if __name__ == "__main__":
    GlobalState.exchange_mount_path = EXCHANGE_MOUNT
    GlobalState.im_daemon_socket_path = IM_SOCKET_PATH
    GlobalState.testbed_package_path = TESTBED_PACKAGE_MOUNT
    GlobalState.start_exec_path = str(os.getcwd())
    
    im = InstanceManager()
    im.run()
