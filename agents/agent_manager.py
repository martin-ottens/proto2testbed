#!/usr/bin/python3

from typing import Any

import subprocess
import json
import socket
import time
import sys

MGMT_SERVER_PORT = 4243
MGMT_SERVER_RETRY = 5
MGMT_SERVER_WAITRETRY = 5
MGMT_SERVER_MAXLEN = 4096

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
                    raise Exception("Unable to connect to managemt server in timeout!")

                time.sleep(MGMT_SERVER_WAITRETRY)
                self.socket.close()
                self.socket = None

                retries_left -= 1

    def stop(self) -> None:
        if self.socket != None:
            self.socket.close()

    def send_started(self, hostname):
        self.socket.sendall(json.dumps({"hostname": hostname, "status": "started"}).encode("utf-8"))

    def send_installed(self, hostname):
        self.socket.sendall(json.dumps({"hostname": hostname, "status": "installed"}).encode("utf-8"))

    def wait_for_command(self) -> Any:
        result = self.socket.recv(ManagementClient.__MAX_FRAME_LEN)
        return json.loads(result.decode("utf-8"))


def get_hostname() -> str:
    return socket.getfqdn()

def get_default_gateway() -> str:
    proc = subprocess.run(["/usr/sbin/ip", "-json", "route"], capture_output=True, shell=False)
    if proc.returncode != 0:
        raise Exception(f"Unable to run '/usr/sbin/ip -j route': {proc.stderr}")

    routes = json.loads(proc.stdout)
    for route in routes:
        if not "dst" in route or not "gateway" in route:
            continue

        if route["dst"] == "default":
            return route["gateway"]
    
    raise Exception(f"Unable to obtain default route!")

def main():
    hostname = get_hostname()
    mg = ManagementClient(("127.0.0.1", MGMT_SERVER_PORT))
    mg.start()
    mg.send_installed(hostname)
    print(mg.wait_for_command())
    mg.send_started(hostname)
    print(mg.wait_for_command())
    mg.stop()

if __name__ == "__main__":
    main()
