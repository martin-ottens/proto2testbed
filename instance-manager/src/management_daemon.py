import socket
import os
import json
import sys

from threading import Thread, Event, Lock
from typing import List, Optional

from preserve_handler import PreserveHandler
from management_client import ManagementClient, DownstreamMassage
from common.instance_manager_message import InstanceMessageType

class IMClientThread(Thread):
    client_id: int = 0
    id_lock = Lock()
    def next_client() -> int:
        with IMClientThread.id_lock:
            IMClientThread.client_id += 1
            return IMClientThread.client_id

    def __init__(self, client_socket: socket, manager: ManagementClient, preserver: PreserveHandler):
        Thread.__init__(self)
        self.daemon = True

        self.client_socket = client_socket
        self.id = IMClientThread.next_client()
        self.manager = manager
        self.preserver = preserver
        self.shut_down = Event()

    def _respond_to_client(self, ok: bool, message: Optional[str] = None):
        result = {
            "status": "ok" if ok else "error"
            }
        if message is not None:
            result["message"] = message
            print(f"Daemon Thread: Client {self.id}: {message}", file=sys.stderr, flush=True)

        self.client_socket.sendall(json.dumps(result).encode("utf-8") + b'\n')
        return ok

    def _handle_preserve(self, data) -> bool:
        if "path" not in data:
            return self._respond_to_client(False, "'path' missing for preserve")

        if not isinstance(data["path"], str):
            return self._respond_to_client(False, "Field 'path' is not a string")
        path = data["path"]

        self.preserver.add(path)
        return self._respond_to_client(True)
        
    def _handle_log(self, data) -> bool:
        if "level" not in data or "message" not in data:
            return self._respond_to_client(False, "'message' or 'level' missing for log")
        
        type = None
        match data["level"]:
            case "SUCCESS":
                type = InstanceMessageType.MSG_SUCCESS
            case "INFO":
                type = InstanceMessageType.MSG_INFO
            case "WARNING":
                type = InstanceMessageType.MSG_WARNING
            case "ERROR":
                type = InstanceMessageType.MSG_ERROR
            case "DEBUG":
                type = InstanceMessageType.MSG_DEBUG
            case _:
                return self._respond_to_client(False, f"Invalid log level '{data['level']}'")
            
        if not isinstance(data["message"], str):
            return self._respond_to_client(False, f"Field 'message' is not a string")
        
        message: DownstreamMassage = DownstreamMassage(type, data["message"])
        self.manager.send_to_server(message)
        return self._respond_to_client(True)
    
    def _handle_data(self, data) -> bool:
        if "measurement" not in data or "tags" not in data or "points" not in data:
            return self._respond_to_client(False, "'measurement', 'tags' or 'points' missing for data")
        
        if not isinstance(data["measurement"], str):
            return self._respond_to_client(False, f"Field 'measurement' is not a string")
        measurement = data["measurement"]
        
        if not isinstance(data["tags"], dict):
            return self._respond_to_client(False, "'tags' is not a dict of strings")
        
        if not all((isinstance(key, str) and isinstance(value, str)) for key, value in data["tags"].items()):
            return self._respond_to_client(False, "'tags' contains invalid keys or values")
        tags = data["tags"]
        
        if not isinstance(data["points"], dict) or not len(data["points"]):
            return self._respond_to_client(False, "'points' has no values or is invalid")

        if not all((isinstance(key, str) and isinstance(value, (int, float))) for key, value in data["points"].items()):
            return self._respond_to_client(False, "'points' contains non float or int values")
        points = data["points"]
        
        self.manager.send_data_point(measurement, points, tags)
        return self._respond_to_client(True)

    def _process_one_message(self, data) -> bool:
        json_data = json.loads(data)
        if "type" not in json_data:
            return self._respond_to_client(False, "Field 'type' not in message")
        
        print(f"Daemon Thread: Client {self.id} issued command: {json_data['type']}", file=sys.stderr, flush=True)

        match json_data["type"]:
            case "status":
                return self._respond_to_client(True)
            case "preserve":
                return self._handle_preserve(json_data)
            case "log":
                return self._handle_log(json_data)
            case "data":
                return self._handle_data(json_data)
            case _:
                return self._respond_to_client(False, f"Invalid 'type' {json_data['type']}")

    def _check_if_valid_json(self, str) -> bool:
        try:
            json.loads(str)
            return True
        except Exception as _:
            return False

    def run(self):
        self.shut_down.clear()
        self.client_socket.settimeout(0.5)
        print(f"Daemon Thread: Client {self.id} connected", file=sys.stderr, flush=True)

        partial_data = ""

        while not self.shut_down.is_set():
            try:
                data = self.client_socket.recv(4096)
                if len(data) == 0:
                    print(f"Daemon Thread: Client {self.id} disconnected (0 bytes read)", file=sys.stderr, flush=True)
                    break

                partial_data = partial_data + data.decode("utf-8")

                if "}\n{" in partial_data:
                    parts = partial_data.split("}\n{")
                    partial_data = ""
                    parts[0] = parts[0] + "}"

                    if len(parts) >= 3:
                        for i in range(1, len(parts) - 1):
                            parts[i] = "{" + parts[i] + "}"
                    
                    if len(parts) >= 2:
                        parts[len(parts) - 1] = "{" + parts[len(parts) - 1]
                    else:
                        partial_data = "{"
                    
                    while len(parts) > 0:
                        part = parts.pop(0)

                        if self._check_if_valid_json(part):
                            if not self._process_one_message(part):
                                break
                        else:
                            while len(parts) > 0:
                                partial_data = parts.pop() + partial_data
                            partial_data = part + partial_data
                            break

                else:
                    if self._check_if_valid_json(partial_data):
                        if not self._process_one_message(partial_data):
                            break
                        partial_data = ""

            except socket.timeout:
                continue
            except Exception as ex:
                print(f"Daemon Thread: Client {self.id} error: {ex}", file=sys.stderr, flush=True)
                raise ex
                break
        
        print(f"Daemon Thread: Client {self.id}: Connection closed.", file=sys.stderr, flush=True)
        self.client_socket.close()

    def stop(self):
        self.shut_down.set()

class IMDaemonServer():
    def __init__(self, manager: ManagementClient, socket_path: str, preserver: PreserveHandler):
        self.manager = manager
        self.socket_path = socket_path
        self.preserver = preserver
        self.shut_down = Event()
        self.client_threads: List[IMClientThread] = []
        self.is_started = False

    def _accept_thread(self):
        while True:
            try:
                client_socket, _ = self.server_sock.accept()
                if self.shut_down.is_set():
                    break
                
                try:
                    client_thread = IMClientThread(client_socket, self.manager, self.preserver)
                    client_thread.start()
                    self.client_threads.append(client_thread)
                except:
                    pass
            except socket.timeout:
                pass

    def start(self):
        self.shut_down.clear()
        try:
            os.unlink(self.socket_path)
        except Exception as ex:
            if os.path.exists(self.socket_path):
                raise ex
        
        self.server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_sock.bind(self.socket_path)
        os.chmod(self.socket_path, mode=0o777)
        self.server_sock.listen(4)

        self.server_thread = Thread(target=self._accept_thread, daemon=True)
        self.server_thread.start()
        self.is_started = True
    
    def stop(self):
        if not self.is_started:
            return

        self.shut_down.set()
        try:
            poison_pill = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            poison_pill.settimeout(1)
            poison_pill.connect(self.socket_path)
            poison_pill.close()
        except Exception:
            pass

        for client in self.client_threads:
            client.stop()
        for client in self.client_threads:
            client.join()

        self.server_thread.join()
        self.server_sock.close()
        self.is_started = False
