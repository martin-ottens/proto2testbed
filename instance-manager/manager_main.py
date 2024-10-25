#!/usr/bin/python3

import subprocess
import json
import os
import shutil

from threading import Barrier
from pathlib import Path

from management_client import ManagementClient, DownstreamMassage, get_hostname
from application_controller import ApplicationController

from common.instance_manager_message import *

FILE_SERVER_PORT = 4242
STATE_FILE = "/tmp/im-setup-succeeded"
TESTBED_PACKAGE_MOUNT = "/opt/testbed"

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

def main():
    instance_name = get_hostname()
    manager = None
    exec_dir = None
    try:
        manager = ManagementClient()
        manager.start()

        # 1. Instance is started
        message = DownstreamMassage(InstanceStatus.STARTED)
        manager.send_to_server(message)

        if not Path(STATE_FILE).is_file():
            # 2. Install instance and report status
            # 2.1. Get initialization data from management server
            installation_data = manager.wait_for_command()
            if "status" not in installation_data or installation_data.get("status") != "initialize":
                raise Exception("Invalid message received from management server")

            if "script" not in installation_data or "environment" not in installation_data:
                raise Exception("Initialization message error: Fields are missing")

            if not isinstance(installation_data.get("environment"), dict):
                raise Exception("Initialization message error: Environment should be a dict")
            
            installation_data["environment"]["TESTBED_PACKAGE"] = TESTBED_PACKAGE_MOUNT
            
            init_message = InitializeMessageUpstream(**installation_data)

            # 2.2 Mount the testbed package from host via virtio p9
            os.mkdir(TESTBED_PACKAGE_MOUNT, mode=0o777)
            proc = None
            try:
                proc = subprocess.run(["mount", "-t", "9p", "-o", "trans=virtio", "tbp", TESTBED_PACKAGE_MOUNT])
            except Exception as ex:
                message = DownstreamMassage(InstanceStatus.FAILED, f"Unable to mount testbed package!")
                manager.send_to_server(message)
                raise Exception("Unable to mount testbed package!") from ex
            
            if proc is not None and proc.returncode != 0:
                message = DownstreamMassage(InstanceStatus.FAILED, 
                                                f"Mounting of testbed package failed with code ({proc.returncode})\nSTDOUT: {proc.stdout.decode('utf-8')}\nSTDERR: {proc.stderr.decode('utf-8')}")
                manager.send_to_server(message)
                raise Exception(f"Unable to mount testbed package: {proc.stderr}")

            # 2.3 Execute the setup script from mounted testbed package
            if init_message.script is not None:
                os.chdir(TESTBED_PACKAGE_MOUNT)
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

                Path(STATE_FILE).touch()

        # 2.4. Report status to management server
        message = DownstreamMassage(InstanceStatus.INITIALIZED)
        manager.send_to_server(message)

        # 3. Get applications
        while True:
            application_data = manager.wait_for_command()
            applications = ApplicationsMessageUpstream.from_json(application_data)
            
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
            
    except Exception as ex:
        raise ex
    finally:
        if exec_dir is not None:
            shutil.rmtree(exec_dir)
        if manager is not None:
            manager.stop()

if __name__ == "__main__":
    main()
