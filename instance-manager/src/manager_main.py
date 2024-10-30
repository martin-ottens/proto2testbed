#!/usr/bin/python3

import subprocess
import json
import os
import shutil
import time
import sys

from threading import Barrier
from pathlib import Path

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


def get_default_gateway() -> str:
    proc = subprocess.run(["/usr/sbin/ip", "-json", "route"], capture_output=True, shell=False)
    if proc.returncode != 0:
        raise Exception(f"Unable to run '/usr/sbin/ip -json route': {proc.stderr}")

    routes = json.loads(proc.stdout)
    for route in routes:
        if not "dst" in route or not "gateway" in route:
            continue

        if route["dst"] == "default":
            return route["gateway"]
    
    raise Exception(f"Unable to obtain default route!")


def handle_experiment(payload, manager, instance_name):
    applications = ApplicationsMessageUpstream.from_json(payload)
            
    barrier = Barrier(len(applications.applications) + 1)
    threads: List[ApplicationController] = []
    for application in applications.applications:
        t = ApplicationController(application, manager, barrier, instance_name)
        t.start()
        threads.append(t)
            
    barrier.wait()
            
    failed = 0
    for t in threads:
        t.join()
        if t.error_occured():
            failed += 1
    
    if failed != 0:
        message = DownstreamMassage(InstanceStatus.EXPERIMENT_FAILED, 
                                    f"{failed} Applications(s) failed.")
        manager.send_to_server(message)
    else:
        message = DownstreamMassage(InstanceStatus.EXPERIMENT_DONE)
        manager.send_to_server(message)

def handle_finish(application_data, preserver: PreserveHandler, manager: ManagementClient):
    print(f"Starting File Preservation", file=sys.stderr, flush=True)
    finish_message = FinishInstanceMessageUpstream(**application_data)
    preserver.batch_add(finish_message.preserve_files)
    preserve_status = InstanceStatus.FAILED
    if preserver.preserve():
        preserve_status = InstanceStatus.FINISHED
    message = DownstreamMassage(preserve_status)
    manager.send_to_server(message)
    print(f"File preservation completed, Instance ready for shut down", file=sys.stderr, flush=True)

def main():
    instance_name = get_hostname()
    manager = None
    preserver = None
    exec_dir = None
    daemon = None
    try:
        # 0. Setup Instance Manager
        manager = ManagementClient(instance_name)
        manager.start()
        preserver = PreserveHandler(manager, EXCHANGE_MOUNT, EXCHANGE_P9_DEV)
        daemon = IMDaemonServer(manager, IM_SOCKET_PATH, preserver)
        daemon.start()

        # 1. Instance is started
        message = DownstreamMassage(InstanceStatus.STARTED)
        manager.send_to_server(message)

        if not Path(STATE_FILE).is_file():
            # 2. Install instance and report status
            # 2.1. Get initialization data from management server
            installation_data = manager.wait_for_command()
            if "status" not in installation_data or installation_data.get("status") != InstanceStatus.INITIALIZED.value:
                # Finish before initialization is finished -> untypical and just for debugging.
                if "status" in installation_data and installation_data.get("status") == InstanceStatus.FINISHED.value:
                    handle_finish(application_data, preserver, manager)
                    while True: time.sleep(1)
                else:
                    raise Exception("Invalid message received from management server")

            if "script" not in installation_data or "environment" not in installation_data:
                raise Exception("Initialization message error: Fields are missing")

            if not isinstance(installation_data.get("environment"), dict):
                raise Exception("Initialization message error: Environment should be a dict")
            
            print(f"Got 'initialize' instructions from Management Server", file=sys.stderr, flush=True)
            
            installation_data["environment"]["TESTBED_PACKAGE"] = TESTBED_PACKAGE_MOUNT
            
            init_message = InitializeMessageUpstream(**installation_data)

            # 2.2 Mount the testbed package from host via virtio p9
            if not os.path.ismount(TESTBED_PACKAGE_MOUNT):
                os.mkdir(TESTBED_PACKAGE_MOUNT, mode=0o777)
                proc = None
                try:
                    proc = subprocess.run(["mount", "-t", "9p", "-o", "trans=virtio", TESTBED_PACKAGE_P9_DEV, TESTBED_PACKAGE_MOUNT])
                except Exception as ex:
                    message = DownstreamMassage(InstanceStatus.FAILED, f"Unable to mount testbed package!")
                    manager.send_to_server(message)
                    raise Exception("Unable to mount testbed package!") from ex
                
                if proc is not None and proc.returncode != 0:
                    message = DownstreamMassage(InstanceStatus.FAILED, 
                                                    f"Mounting of testbed package failed with code ({proc.returncode})\nSTDOUT: {proc.stdout.decode('utf-8')}\nSTDERR: {proc.stderr.decode('utf-8')}")
                    manager.send_to_server(message)
                    raise Exception(f"Unable to mount testbed package: {proc.stderr}")
                print(f"Testbed Package mounted to {TESTBED_PACKAGE_P9_DEV}", file=sys.stderr, flush=True)

            # 2.3 Execute the setup script from mounted testbed package
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
                    message = DownstreamMassage(InstanceStatus.FAILED, 
                                                f"Setup script failed:\nMESSAGE: {ex}")
                    manager.send_to_server(message)
                    raise Exception(f"Unable to run setup_script") from ex
                
                if proc is not None and proc.returncode != 0:
                    message = DownstreamMassage(InstanceStatus.FAILED, 
                                                f"Setup script failed ({proc.returncode})\nSTDOUT: {proc.stdout.decode('utf-8')}\nSTDERR: {proc.stderr.decode('utf-8')}")
                    manager.send_to_server(message)
                    raise Exception(f"Unable to run setup_script': {proc.stderr}")
                print(f"Execution of setup script {init_message.script} completed", file=sys.stderr, flush=True)
                Path(STATE_FILE).touch()
            else:
                print(f"No setup script in 'initialize' message, skipping setup.", file=sys.stderr, flush=True)

        # 2.4. Report status to management server
        message = DownstreamMassage(InstanceStatus.INITIALIZED)
        manager.send_to_server(message)

        # 3. Get applications / finish instructions
        while True:
            print(f"Waiting for Applications or 'finish' message ...", file=sys.stderr, flush=True)
            application_data = manager.wait_for_command()

            if application_data["status"] == ApplicationsMessageUpstream.status_name:
                print(f"Starting execution of Applications", file=sys.stderr, flush=True)
                handle_experiment(application_data, manager, instance_name)
            elif application_data["status"] == FinishInstanceMessageUpstream.status_name:
                handle_finish(application_data, preserver, manager)
                while True: time.sleep(1)
            else:
                raise Exception(f"Invalid Upstream Message Package received: {application_data['status']}")
            
            
    except Exception as ex:
        raise ex
    finally:
        print(f"Instance Manager is shutting down", file=sys.stderr, flush=True)
        if daemon is not None:
            daemon.stop()
        if manager is not None:
            manager.stop()
        if exec_dir is not None:
            shutil.rmtree(exec_dir)


if __name__ == "__main__":
    main()
