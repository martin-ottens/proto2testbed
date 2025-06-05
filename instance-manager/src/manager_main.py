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
import time
import jsonpickle

from pathlib import Path
from enum import Enum, auto
from typing import Optional, List

from preserve_handler import PreserveHandler
from management_daemon import IMDaemonServer
from management_client import ManagementClient, DownstreamMessage, get_hostname
from application_manager import ApplicationManager
from global_state import GlobalState

from common.instance_manager_message import *
from common.application_configs import AppStartStatus


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
        self.delayed_application_messages: List[DownstreamMessage] = []

    def message_to_controller(self, message_type: InstanceMessageType, payload = None):
        self.manager.send_to_server(DownstreamMessage(message_type, payload))

    def handle_initialize(self, init_message: InitializeMessageUpstream) -> bool:
        print(f"Got 'initialize' instructions from Management Server", file=sys.stderr, flush=True)

        init_message.environment["TESTBED_PACKAGE"] = GlobalState.testbed_package_path

        # 1. Mount the testbed package from host via virtio p9 (if not already done)
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
                return False
            
            print(f"Testbed Package mounted to {TESTBED_PACKAGE_P9_DEV}", file=sys.stderr, flush=True)

        # 2. Execute the setup script from mounted testbed package
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

        # 3. Report status to management server
        Path(STATE_FILE).touch()
        self.message_to_controller(InstanceMessageType.INITIALIZED)
        return True

    def install_apps(self, applications: InstallApplicationsMessageUpstream) -> bool:
        print(f"Starting installation of Applications", file=sys.stderr, flush=True)

        if self.application_manager is not None:
            print(f"Purging previous installed application_manager")
            del self.application_manager
        
        self.application_manager = ApplicationManager(self, self.manager, self.instance_name)

        return self.application_manager.install_apps(applications.applications)
    
    def sync_ptp_clock(self) -> bool:
        proc = None
        try:
            proc = subprocess.run(["chronyc", "makestep"])
        except Exception as ex:
            self.message_to_controller(InstanceMessageType.FAILED, f"Unable to sync ptp clock: {ex}")
            return False

        if proc is not None and proc.returncode != 0:
            self.message_to_controller(InstanceMessageType.FAILED, 
                                       f"Syncing of ptp clock failed with exit code ({proc.returncode})\nSTDERR: {proc.stderr.decode('utf-8')}")
            print(f"Unable sync ptp clock': {proc.stderr.decode('utf-8')}", file=sys.stderr, flush=True)
            return False
        else:
            return True

    def run_apps(self, config: RunApplicationsMessageUpstream) -> bool:
        if self.application_manager is None:
            print("Unable to run experiment: No application manager is installed")
            self.message_to_controller(InstanceMessageType.MSG_ERROR, 
                                   f"Can't run Applications: No applications manager is configured.")
            return False
        
        if config.t0 < time.time():
            print("Clock of this instance is running behind!")
            self.message_to_controller(InstanceMessageType.MSG_ERROR, 
                                   f"Unable to start Applications at t0: Clock is running behind.")
            return False
        
        return self.application_manager.run_initial_apps(config.t0)
    
    def run_deferred_app(self, message: ApplicationStatusMessageUpstream) -> None:
        if self.application_manager is None:
            print("Unable to start Application: No application manager is installed")
            self.message_to_controller(InstanceMessageType.MSG_ERROR, 
                                   f"Can't start Application: No applications manager is configured.")
            return
        
        self.application_manager.run_deferred_app(message.app_name, message.app_status)

    def handle_finish(self, finish_message: FinishInstanceMessageUpstream) -> False:
        print(f"Starting File Preservation", file=sys.stderr, flush=True)

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
        
    def handle_file_copy(self, copy_instructions: CopyFileMessageUpstream) -> bool:
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
        message = DownstreamMessage(InstanceMessageType.COPIED_FILE, copy_instructions.proc_id)
        self.manager.send_to_server(message)
        return True
    
    def single_app_status_changed(self, app: str, status: AppStartStatus) -> None:
        if status not in [AppStartStatus.FINISH, AppStartStatus.START]:
            return

        messagetype = InstanceMessageType.APP_FINISHED_SIGNAL if status == AppStartStatus.FINISH else InstanceMessageType.APP_STARTED_SIGNAL
        message = DownstreamMessage(messagetype, app)

        if self.state not in [IMState.EXPERIMENT_RUNNING, IMState.FAILED, IMState.READY_FOR_SHUTDOWN]:
            self.delayed_application_messages.append(message)
        else:
            self.manager.send_to_server(message)

    def all_apps_status_changed(self, failed_count: int) -> None:
        if failed_count != 0:
            print(f"Execution of Applications finished, {failed_count} failed.", file=sys.stderr, flush=True)
            message = DownstreamMessage(InstanceMessageType.APPS_FAILED, f"{failed_count} Applications(s) failed.")
        else:
            print(f"Execution of all Applications successfully completed.", file=sys.stderr, flush=True)
            message = DownstreamMessage(InstanceMessageType.APPS_DONE)

        if self.state not in [IMState.EXPERIMENT_RUNNING, IMState.FAILED, IMState.READY_FOR_SHUTDOWN]:
            self.delayed_application_messages.append(message)
        else:
            self.manager.send_to_server(message)

    def _run_instance_manager(self):
        self.manager.start()
        self.daemon.start()

        self.message_to_controller(InstanceMessageType.STARTED)

        # Already initialized, let the controller know
        if Path(STATE_FILE).is_file():
            self.state = IMState.INITIALIZED
            self.message_to_controller(InstanceMessageType.INITIALIZED)
        
        while True:
            data_str = self.manager.wait_for_command()
            data = jsonpickle.decode(data_str)

            match data:
                case InitializeMessageUpstream():
                    if self.state != IMState.STARTED:
                        print(f"Got 'initialize' message from controller, but im in state {self.state.value}, skipping init.")
                        self.message_to_controller(InstanceMessageType.INITIALIZED)
                    else:
                        if self.handle_initialize(data):
                            self.state = IMState.INITIALIZED
                        else:
                            self.state = IMState.FAILED
                case InstallApplicationsMessageUpstream():
                    if self.state != IMState.INITIALIZED and self.state != IMState.APPS_READY:
                        print(f"Got 'install_apps' message from controller, but im in state {self.state.value}, skipping.")
                        self.message_to_controller(InstanceMessageType.MSG_ERROR, "Instance is not ready for app installation.")
                    else:
                        self.install_apps(data)
                        self.state = IMState.APPS_READY
                case RunApplicationsMessageUpstream():
                    if self.state != IMState.APPS_READY:
                        print(f"Got 'run_apps' message from controller, but im in state {self.state.value}, skipping.")
                        self.message_to_controller(InstanceMessageType.MSG_ERROR, "Instance has not yet installed apps.")
                    else:
                        self.state = IMState.EXPERIMENT_RUNNING

                        for message in self.delayed_application_messages:
                            self.manager.send_to_server(message)

                        if not self.sync_ptp_clock():
                            self.state = IMState.FAILED
                        else:
                            if not self.run_apps(data):
                                self.state = IMState.FAILED
                case ApplicationStatusMessageUpstream():
                    if self.state != IMState.EXPERIMENT_RUNNING:
                        print(f"Got message from controller to start deferred, but im in state {self.state.value}")
                        self.message_to_controller(InstanceMessageType.MSG_ERROR, "Starting deferred Applications in invalid state!")

                    self.run_deferred_app(data)
                case CopyFileMessageUpstream():
                    if not self.handle_file_copy(data):
                        self.state = IMState.FAILED
                case FinishInstanceMessageUpstream():
                    if self.handle_finish(data):
                        self.state = IMState.READY_FOR_SHUTDOWN
                    else:
                        self.state = IMState.FAILED
                case _:
                    raise Exception(f"Invalid 'status' in message: {type(data)}")
            
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
