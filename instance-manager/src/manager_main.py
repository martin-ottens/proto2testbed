#!/usr/bin/python3

import subprocess
import os
import shutil
import sys

from threading import Barrier
from pathlib import Path
from enum import Enum, auto

from preserve_handler import PreserveHandler
from management_daemon import IMDaemonServer
from management_client import ManagementClient, DownstreamMassage, get_hostname
from application_controller import ApplicationController

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
    EXPERIMENT_RUNNING = auto()
    READY_FOR_SHUTDOWN = auto()
    FAILED = auto()


class InstanceManager():
    
    def __init__(self):
        self.instance_name = get_hostname()
        self.manager = ManagementClient(self.instance_name)
        self.preserver = PreserveHandler(self.manager, EXCHANGE_MOUNT, EXCHANGE_P9_DEV)
        self.exec_dir = None
        self.daemon = IMDaemonServer(self.manager, IM_SOCKET_PATH, self.preserver)
        self.state = IMState.STARTED

    def message_to_controller(self, type: InstanceMessageType, payload = None):
        self.manager.send_to_server(DownstreamMassage(type, payload))

    def handle_initialize(self, data) -> bool:
        # 1. Check initialization data from management server
        if "script" not in data or "environment" not in data:
            raise Exception("Initialization message error: Fields are missing")

        if not isinstance(data.get("environment"), dict):
            raise Exception("Initialization message error: Environment should be a dict")

        print(f"Got 'initialize' instructions from Management Server", file=sys.stderr, flush=True)

        data["environment"]["TESTBED_PACKAGE"] = TESTBED_PACKAGE_MOUNT

        init_message = InitializeMessageUpstream(**data)

        # 2. Mount the testbed package from host via virtio p9 (if not already done)
        if not os.path.ismount(TESTBED_PACKAGE_MOUNT):
            os.mkdir(TESTBED_PACKAGE_MOUNT, mode=0o777)
            proc = None
            try:
                proc = subprocess.run(["mount", "-t", "9p", "-o", "trans=virtio", TESTBED_PACKAGE_P9_DEV, TESTBED_PACKAGE_MOUNT])
            except Exception as ex:
                self.message_to_controller(InstanceMessageType.FAILED, f"Unable to mount testbed package!")

            if proc is not None and proc.returncode != 0:
                self.message_to_controller(InstanceMessageType.FAILED, 
                                                        f"Mounting of testbed package failed with code ({proc.returncode})\nSTDOUT: {proc.stdout.decode('utf-8')}\nSTDERR: {proc.stderr.decode('utf-8')}")
                print(f"Testbed Package mounted to {TESTBED_PACKAGE_P9_DEV}", file=sys.stderr, flush=True)

        # 3. Execute the setup script from mounted testbed package
        if init_message.script is not None:
            print(f"Running setup script {init_message.script}", file=sys.stderr, flush=True)
            os.chdir(TESTBED_PACKAGE_MOUNT)

            if init_message.environment is not None:
                for key, value in init_message.environment.items():
                    os.environ[key] = value

                proc = None
                try:
                    proc = subprocess.run(["/bin/bash", init_message.script], capture_output=True, shell=False)
                except Exception as ex:
                    self.message_to_controller(InstanceMessageType.FAILED, f"Setup script failed:\nMESSAGE: {ex}")
                    raise Exception(f"Unable to run setup_script") from ex

                if proc is not None and proc.returncode != 0:
                    self.message_to_controller(InstanceMessageType.FAILED, 
                                                    f"Setup script failed ({proc.returncode})\nSTDOUT: {proc.stdout.decode('utf-8')}\nSTDERR: {proc.stderr.decode('utf-8')}")
                    raise Exception(f"Unable to run setup_script': {proc.stderr}")
                
                print(f"Execution of setup script {init_message.script} completed", file=sys.stderr, flush=True)
            else:
                print(f"No setup script in 'initialize' message, skipping setup.", file=sys.stderr, flush=True)

        # 4. Report status to management server
        Path(STATE_FILE).touch()
        self.message_to_controller(InstanceMessageType.INITIALIZED)
        return True

    def handle_experiment(self, data) -> bool:
        print(f"Starting execution of Applications", file=sys.stderr, flush=True)
        applications = ApplicationsMessageUpstream.from_json(data)

        barrier = Barrier(len(applications.applications) + 1)
        threads: List[ApplicationController] = []
        for application in applications.applications:
            t = ApplicationController(application, self.manager, barrier, self.instance_name)
            t.start()
            threads.append(t)

        barrier.wait()

        failed = 0
        for t in threads:
            t.join()
            if t.error_occured():
                failed += 1

        if failed != 0:
            print(f"Execution of Applications finished, {failed} failed.", file=sys.stderr, flush=True)
            self.message_to_controller(InstanceMessageType.EXPERIMENT_FAILED, 
                                        f"{failed} Applications(s) failed.")
            return False
        else:
            print(f"Execution of Applications successfully completed.", file=sys.stderr, flush=True)
            self.message_to_controller(InstanceMessageType.EXPERIMENT_DONE)
            return True

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
            self.message_to_controller(InstanceMessageType.FAILED)
            print(f"File preservation failed.", file=sys.stderr, flush=True)
            return False
        
    def handle_file_copy(self, data) -> bool:
        copy_instructions = CopyFileMessageUpstream(**data)

        if copy_instructions.proc_id is None:
            self.message_to_controller(InstanceMessageType.MSG_ERROR, 
                                       f"Copy failed, no proc_id was provided to Instance.")
            print(f"Invalid copy instructin packet: proc_id missing!")

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
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(source, target)

            if not source_is_local:
                if source.is_dir():
                    shutil.rmtree(source, ignore_errors=True)
                else:
                    os.remove(source)
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
                case ApplicationsMessageUpstream.status_name:
                    if self.state != IMState.INITIALIZED:
                        print(f"Got 'applications' message from controller, but im in state {self.state.value}, skipping.")
                        self.message_to_controller(InstanceMessageType.MSG_ERROR, "Instance is not yet initialized.")
                        continue

                    self.state = IMState.EXPERIMENT_RUNNING
                    if self.handle_experiment(data):
                        self.state = IMState.INITIALIZED
                    else:
                        self.state = IMState.FAILED
                    continue
                case CopyFileMessageUpstream.status_name:
                    if not self.handle_file_copy(data):
                        self.state = IMState.FAILED
                case FinishInstanceMessageUpstream.status_name:
                    if self.handle_finish(data):
                        self.state = IMState.READY_FOR_SHUTDOWN
                    else:
                        self.state = IMState.FAILED
                    continue
                case _:
                    raise Exception(f"Invalid 'status' in message: {data.get('status')}")
            
            if self.state == IMState.FAILED:
                raise Exception("Instance Manager has entered failed state.")

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
            if self.exec_dir is not None:
                shutil.rmtree(self.exec_dir)


if __name__ == "__main__":
    im = InstanceManager()
    im.run()
