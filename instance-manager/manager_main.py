#!/usr/bin/python3

from typing import Any

import subprocess
import json
import socket
import time
import sys
import os
import tempfile
import shutil
import urllib.request

from common.instance_manager_message import *

FILE_SERVER_PORT = 4242
MGMT_SERVER_PORT = 4243
MGMT_SERVER_RETRY = 5
MGMT_SERVER_WAITRETRY = 5
MGMT_SERVER_MAXLEN = 4096

def get_hostname() -> str:
    return socket.getfqdn()

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

class DownstreamMassage():
    def __init__(self, status, message = None):
        self.message = InstanceManagerDownstream(get_hostname(), status, message)
    
    def set_message(self, message):
            self.message.message = message

    def get_json_bytes(self) -> bytes:
        return self.message.as_json_bytes() + b'\n'

class ManagementClient():
    __MAX_FRAME_LEN = 8192

    def __init__(self, mgmt_server):
        self.mgmt_server = mgmt_server
        self.socket = None

    def __del__(self):
        self.stop()
    
    def start(self) -> None:
        retries_left = MGMT_SERVER_RETRY
        while True:
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.connect(self.mgmt_server)
                return
            except Exception as ex:
                print(f"Unable to connect to {self.mgmt_server}: {ex}", file=sys.stderr, flush=True)

                if retries_left == 0:
                    raise Exception("Unable to connect to managemt server in timeout") from ex

                time.sleep(MGMT_SERVER_WAITRETRY)
                self.socket.close()
                self.socket = None

                retries_left -= 1

    def stop(self) -> None:
        if self.socket != None:
            self.socket.close()
            self.socket = None

    def send_to_server(self, downstream_message: DownstreamMassage):
        try:
            self.socket.sendall(downstream_message.get_json_bytes())
        except Exception as ex:
            raise Exception("Unable to send message to management server") from ex

    def wait_for_command(self) -> Any:
        try:
            self.socket.settimeout(None)
            result = self.socket.recv(ManagementClient.__MAX_FRAME_LEN)
            if len(result) == 0:
                raise Exception("Management server has disconnected")
            return json.loads(result.decode("utf-8"))
        except Exception as ex:
            raise Exception("Unable to read message from management server") from ex


def main():
    management_server_addr = get_default_gateway()
    manager = None
    exec_dir = None
    try:
        manager = ManagementClient((management_server_addr, MGMT_SERVER_PORT, ))
        manager.start()

        # 1. Instance is started
        message = DownstreamMassage("started")
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
                message = DownstreamMassage("failed", "Unable to fetch script file")
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
                message = DownstreamMassage("failed", 
                                            f"Setup script failed:\nMESSAGE: {ex}")
                manager.send_to_server(message)
                raise Exception(f"Unable to run setup_script") from ex
            
            if proc is not None and proc.returncode != 0:
                message = DownstreamMassage("failed", 
                                            f"Setup script failed ({proc.returncode})\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}")
                manager.send_to_server(message)
                raise Exception(f"Unable to run setup_script': {proc.stderr}")

        # 2.4. Report status to management server
        message = DownstreamMassage("initialized")
        manager.send_to_server(message)

        experiment_data = manager.wait_for_command()
        print(ExperimentMessageUpstream.from_json(experiment_data).experiments[0].settings, flush=True)
        time.sleep(1000000)
    except Exception as ex:
        raise ex
    finally:
        if exec_dir is not None:
            shutil.rmtree(exec_dir)
        if manager is not None:
            manager.stop()

if __name__ == "__main__":
    main()
