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

import socket
import time
import sys
import serial
import os

from typing import Any, Dict, Optional
from threading import Lock
from abc import ABC, abstractmethod

from common.instance_manager_message import *

MGMT_SERVER_RETRY = 5
MGMT_SERVER_WAITRETRY = 5
MGMT_SERVER_MAXLEN = 4096
MGMT_SERVER_SERIAL = "/dev/ttyS1"
MGMT_SERVER_SERIAL_BAUDRATE = 256000 # Speeeed. All we got with pci-serial.
MGMT_SERVER_SERIAL_TIMEOUT = 1

MGMT_SERVER_VSOCK_PORT = 424242
MGMT_SERVER_VSOCK_TIMEOUT = 30


def get_hostname() -> str:
    return socket.getfqdn()


class DownstreamMassage:
    def __init__(self, status: InstanceMessageType, message = None):
        self.message = InstanceManagerDownstream(get_hostname(), str(status), message)
    
    def set_message(self, message):
            self.message.message = message

    def get_json_bytes(self) -> bytes:
        return self.message.to_json().encode("utf-8") + b'\n'


class ManagementServerConnection(ABC):
    @abstractmethod
    def connect(self) -> bool:
        pass

    @abstractmethod
    def close(self):
        pass

    @abstractmethod
    def read(self) -> Optional[bytes]:
        pass

    @abstractmethod
    def write(self, data: bytes):
        pass

    @abstractmethod
    def settimeout(self, timeout: Optional[int]):
        pass


class SerialServerConnection(ManagementServerConnection):
    def __init__(self, device: str, baudrate: int, timeout: float, 
                 retries: int, waitretry: int) -> None:
        super().__init__()
        self.device = device
        self.baudrate = baudrate
        self.timeout = timeout
        self.retries = retries
        self.waitretry = waitretry
        self.socket = None

    def connect(self) -> bool:
        retries_left = self.retries
        while True:
            try:
                self.socket = serial.Serial(self.device, self.baudrate, timeout=self.timeout)
                print(f"Opened serial connection to Management Server {self.device}", file=sys.stderr, flush=True)
                return True
            except Exception as ex:
                print(f"Unable to connect to {self.device}: {ex}", file=sys.stderr, flush=True)

                if retries_left == 0:
                    raise Exception("Unable to connect to Management Server in timeout") from ex

                time.sleep(self.waitretry)
                self.socket.close()
                self.socket = None

                retries_left -= 1
    
    def close(self):
        if self.socket is not None:
            self.socket.close()
            self.socket = None

    def read(self) -> Optional[bytes]:
        if self.socket is None:
            return None
        return self.socket.readline()

    def write(self, data: bytes):
        if self.socket is None:
            return
        self.socket.write(data)
    
    def settimeout(self, timeout: Optional[int]):
        if self.socket is None:
            return
        self.socket.timeout = timeout
    

class VsockServerConnection(ManagementServerConnection):
    def __init__(self, port: int, timeout: int):
        super().__init__()
        self.port = port
        self.timeout = timeout
        self.socket = None
        self.connection = None

    def connect(self) -> bool:
        self.socket = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
        self.socket.settimeout(self.timeout)
        self.socket.bind((socket.VMADDR_CID_ANY, self.port))
        self.socket.listen(1)
        self.connection, addr = self.socket.accept()
        print(f"VSOCK connection established to {addr}", file=sys.stderr, flush=True)
        return True
    
    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

        if self.socket is not None:
            self.socket.close()
            self.socket = None
    
    def write(self, data):
        if self.connection is None:
            return
        self.connection.sendall(data)
    
    def read(self) -> Optional[bytes]:
        if self.connection is None:
            return None
        return self.connection.recv(4096)
    
    def settimeout(self, timeout):
        if self.connection is None:
            return
        self.connection.settimeout(timeout)


class ManagementClient():

    @classmethod
    def check_vsock_enabled(cls) -> bool:
        return os.path.exists("/dev/vsock")

    def __init__(self, instance_name: str):
        self.socket = None
        self.instance_name = instance_name
        self.sendlock = Lock()
        self.partial_data = ""

        self.connection: ManagementServerConnection
        if ManagementClient.check_vsock_enabled():
            self.connection = VsockServerConnection(MGMT_SERVER_VSOCK_PORT, MGMT_SERVER_VSOCK_TIMEOUT)
        else:
            self.connection = SerialServerConnection(MGMT_SERVER_SERIAL, MGMT_SERVER_SERIAL_BAUDRATE, 
                                                     MGMT_SERVER_SERIAL_TIMEOUT, MGMT_SERVER_RETRY, 
                                                     MGMT_SERVER_WAITRETRY)

    def __del__(self):
        self.stop()
    
    def start(self) -> None:
        if not self.connection.connect():
            raise Exception("Unable to connect to management server")

    def stop(self) -> None:
        self.connection.close()

    def send_data_point(self, measurement: str, points: Dict[str, int | float], tags: Optional[Dict[str, str]] = None):
        if points is None:
            return

        data = [
            {
                "measurement": measurement,
                "tags": {
                    "instance": self.instance_name,
                },
                "fields": points
            }
        ]

        if tags is not None:
            for k, v in tags.items():
                data[0]["tags"][k] = v

        message: DownstreamMassage = DownstreamMassage(InstanceMessageType.DATA_POINT, data)
        self.send_to_server(message)


    def send_to_server(self, downstream_message: DownstreamMassage):
        try:
            with self.sendlock:
                self.connection.write(downstream_message.get_json_bytes())
        except Exception as ex:
            raise Exception("Unable to send message to management server") from ex
    
    def _check_if_valid_json(self, json_str: str) -> bool:
        try:
            json.loads(json_str)
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
            self.connection.settimeout(None)
            result = self.connection.read()
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
