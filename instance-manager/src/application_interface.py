import json
import socket
import sys

from typing import Dict, Optional

from applications.generic_application_interface import LogMessageLevel, GenericApplicationInterface
from global_state import GlobalState


class ApplicationInterface(GenericApplicationInterface):
    def __init__(self, app_name: str, socket_path: str):
        super().__init__(app_name, socket_path)

    def connect(self):
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(1)
        self.socket.connect(self.socket_path)

    def __is_connected(self) -> bool:
        try:
            data = self.socket.recv(8, socket.MSG_DONTWAIT | socket.MSG_PEEK)
            return len(data) != 0
        except BlockingIOError:
            return True
        except Exception:
            return True

    def disconnect(self):
        if self.socket is None:
            return
        
        self.socket.close()
        self.is_connected = False

    def _send_to_daemon(self, payload) -> bool:
        if not self.__is_connected():
            try:
                print("Reopening previously closed connection to Instance Manager Daemon", file=sys.stderr, flush=True)
                self.connect()
            except Exception as ex:
                print(f"Unable to reopen connection Instance Manager Daemon: {ex}", file=sys.stderr, flush=True)
                return False

        if not isinstance(payload, dict) or "type" not in payload:
            return False
        else:
            payload["app"] = self.app_name
        
        try:
            self.socket.sendall(json.dumps(payload).encode("utf-8") + b'\n')
            result = self.socket.recv(4096)
            result_obj = json.loads(result)
            status = result_obj["status"]
            if status != "ok":
                result_message = result_obj.get("message", None)
                print(f"Application Interface: Error from Instance Manager Daemon: {result_message}", file=sys.stderr, flush=True)

            return status == "ok"
        except Exception as ex:
            print(f"Unable to communicate to Instance Manager Daemon: {ex}", file=sys.stderr, flush=True)
            return False

    def log(self, level: LogMessageLevel, message: str) -> bool:
        payload = {
            "type": "log",
            "level": str(level),
            "message": f"App {self.app_name}: {message}"
        }
        return self._send_to_daemon(payload)

    def data_point(self, series_name: str, points: Dict[str, int | float], additional_tags: Optional[Dict[str, str]] = None) -> bool:
        payload = {
            "type": "data",
            "measurement": series_name,
            "points": points,
        }

        if additional_tags is None:
            payload["tags"] = {}
        else:
            payload["tags"] = additional_tags

        # tags.instance will be added by Instance Manager Daemon
        payload["tags"]["application"] = self.app_name

        return self._send_to_daemon(payload)

    def preserve_file(self, path: str) -> bool:
        payload = {
            "type": "preserve",
            "path": path
        }

        return self._send_to_daemon(payload)
    
    def get_global_state() -> GlobalState:
        return GlobalState


