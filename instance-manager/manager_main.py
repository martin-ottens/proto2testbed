#!/usr/bin/python3

import subprocess
import json
import os
import tempfile
import shutil
import urllib.request
from threading import Barrier

from management_client import ManagementClient, DownstreamMassage, get_hostname
from collector_controller import CollectorController

from common.instance_manager_message import *

FILE_SERVER_PORT = 4242
MGMT_SERVER_PORT = 4243

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
    management_server_addr = get_default_gateway()
    instance_name = get_hostname()
    manager = None
    exec_dir = None
    try:
        manager = ManagementClient((management_server_addr, MGMT_SERVER_PORT, ))
        manager.start()

        # 1. Instance is started
        message = DownstreamMassage(InstanceStatus.STARTED)
        manager.send_to_server(message)

        # 2. Install instance and report status
        # 2.1. Get initialization data from management server
        installation_data = manager.wait_for_command()
        if "status" not in installation_data or installation_data.get("status") != "initialize":
            raise Exception("Invalid message received from management server")

        if "script" not in installation_data or "environment" not in installation_data:
            raise Exception("Initialization message error: Fields are missing")

        if not isinstance(installation_data.get("environment"), dict):
            raise Exception("Initialization message error: Environment should be a dict")
        
        init_message = InitializeMessageUpstream(**installation_data)

        # 2.2 Download initialization script from file server
        if init_message.script is not None:
            exec_dir = tempfile.mkdtemp()
            setup_script_basename = os.path.basename(init_message.script)
            setup_script = f"{exec_dir}/{setup_script_basename}"
            try:
                urllib.request.urlretrieve(f"http://{management_server_addr}:{FILE_SERVER_PORT}/{init_message.script}", setup_script)
            except Exception as ex:
                message = DownstreamMassage(InstanceStatus.FAILED, "Unable to fetch script file")
                manager.send_to_server(message)
                raise Exception(f"Unable to retrive script file {init_message.script} from file server") from ex

            # 2.3. Setup execution environment and launch script
            os.chmod(setup_script, 0o744)
            os.chdir(exec_dir)
            for key, value in init_message.environment.items():
                os.environ[key] = value
            
            proc = None
            try:
                proc = subprocess.run(["/bin/bash", setup_script_basename], capture_output=True, shell=False)
            except Exception as ex:
                message = DownstreamMassage(InstanceStatus.FAILED, 
                                            f"Setup script failed:\nMESSAGE: {ex}")
                manager.send_to_server(message)
                raise Exception(f"Unable to run setup_script") from ex
            
            if proc is not None and proc.returncode != 0:
                message = DownstreamMassage(InstanceStatus.FAILED, 
                                            f"Setup script failed ({proc.returncode})\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}")
                manager.send_to_server(message)
                raise Exception(f"Unable to run setup_script': {proc.stderr}")

        # 2.4. Report status to management server
        message = DownstreamMassage(InstanceStatus.INITIALIZED)
        manager.send_to_server(message)

        # 3. Get experiments
        while True:
            experiment_data = manager.wait_for_command()
            experiments = ExperimentMessageUpstream.from_json(experiment_data)
            
            barrier = Barrier(len(experiments.experiments) + 1)
            threads: List[CollectorController] = []
            for experiment in experiments.experiments:
                t = CollectorController(experiment, manager, barrier, experiments.influxdb, instance_name)
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
                                            f"{failed} Experiment(s) failed.")
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
