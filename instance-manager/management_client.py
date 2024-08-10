import socket
import time
import sys

from typing import Any
from threading import Lock

from common.instance_manager_message import *

MGMT_SERVER_RETRY = 5
MGMT_SERVER_WAITRETRY = 5
MGMT_SERVER_MAXLEN = 4096

def get_hostname() -> str:
    return socket.getfqdn()

class DownstreamMassage():
    def __init__(self, status: InstanceStatus, message = None):
        self.message = InstanceManagerDownstream(get_hostname(), str(status), message)
    
    def set_message(self, message):
            self.message.message = message

    def get_json_bytes(self) -> bytes:
        return self.message.to_json().encode("utf-8") + b'\n'

class ManagementClient():
    __MAX_FRAME_LEN = 8192

    def __init__(self, mgmt_server):
        self.mgmt_server = mgmt_server
        self.socket = None
        self.sendlock = Lock()
        self.partial_data = ""

    def __del__(self):
        self.stop()
    
    def start(self) -> None:
        retries_left = MGMT_SERVER_RETRY
        while True:
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
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
            with self.sendlock:
                self.socket.sendall(downstream_message.get_json_bytes())
        except Exception as ex:
            raise Exception("Unable to send message to management server") from ex
    
    def _check_if_valid_json(self, str) -> bool:
        try:
            json.loads(str)
            return True
        except Exception as _:
            return False

    def wait_for_command(self) -> Any:
        if len(self.partial_data) != 0:
            if self._check_if_valid_json(self.partial_data):
                tmp = self.partial_data
                self.partial_data = ""
                return json.loads(tmp)

        try:
            self.socket.settimeout(None)
            result = self.socket.recv(ManagementClient.__MAX_FRAME_LEN)
            if len(result) == 0:
                raise Exception("Management server has disconnected")
            
            self.partial_data = self.partial_data + result.decode("utf-8")

            if "}\n{" in self.partial_data:
                # Multipart message
                parts = self.partial_data.split("}\n{", maxsplit=1)
                parts[0] = parts[0] + "}"
                parts[1] = "{" + parts[1]
                self.partial_data = parts[1]
                return json.loads(parts[0])
            else:
                # Singlepart message
                tmp = self.partial_data
                self.partial_data = ""
                return json.loads(tmp)
        except Exception as ex:
            raise Exception("Unable to read message from management server") from ex
