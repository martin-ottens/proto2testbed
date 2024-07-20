import socket
import threading
import json

from loguru import logger
from jsonschema import validate

from utils.interfaces import Dismantable

import state_manager

class ManagementClientConnection(threading.Thread):
    __MAX_FRAME_LEN = 8192

    message_schema = None

    def __init__(self, addr, client_socket: socket, manager: state_manager.MachineStateManager):
        threading.Thread.__init__(self)
        self.addr = addr
        self.client_socket = client_socket
        self.manager = manager
        self.daemon = True
        self.stop_event = threading.Event()
        self.client = None

        if ManagementClientConnection.message_schema is None:
            with open("assets/statusmsg.schema.json", "r") as handle:
                ManagementClientConnection.message_schema = json.load(handle)

    def run(self):
        logger.info(f"Management: Client {self.addr} connected")
        self.client_socket.settimeout(0.5)
        while not self.stop_event.is_set():
            try:
                data = self.client_socket.recv(ManagementClientConnection.__MAX_FRAME_LEN)
                if len(data) == 0:
                    logger.info(f"Management: Client {self.addr} disconnected")
                    break

                try:
                    json_data = json.loads(data.decode("utf-8"))
                    validate(schema=ManagementClientConnection.message_schema, instance=json_data)
                except Exception as ex:
                    logger.opt(exception=ex).error(f"Management: Client {self.addr} message parsing error")
                    break

                if self.client is None:
                    self.client = self.manager.get_machine(json_data["name"])
                    if self.client is None:
                        logger.error(f"Management: Client {self.addr} reported invalid instance name: {json_data['name']}")
                        break
                    self.client.connect(self.addr, self)
                else:
                    if self.client.name != json_data["name"]:
                        logger.error(f"Management: Client {self.addr} reported name {self.client.name} before, now {json_data['name']}")
                        break

                match json_data["status"]:
                    case "started":
                        self.client.set_state(state_manager.AgentManagementState.STARTED)
                        logger.info(f"Management: Client {self.client.name} started. Sending setup instructions.")
                        self.send_message(json.dumps({
                            "status": "initialize",
                            "script": self.client.get_setup_env()[0],
                            "environment": self.client.get_setup_env()[1]
                        }).encode("utf-8"))
                    case "initialized":
                        self.client.set_state(state_manager.AgentManagementState.INITIALIZED)
                        logger.info(f"Management: Client {self.client.name} initialized.")
                    case "message":
                        pass
                    case "failed":
                        self.client.set_state(state_manager.AgentManagementState.FAILED)
                        if "message" in json_data:
                            logger.error(f"Management: Client {self.client.name} reported failure with message: {json_data['message']}.")
                        else:
                            logger.error(f"Management: Client {self.client.name} reported failure without message.")
                        break
                    case _:
                        logger.warning(f"Management: Client {self.client.name}: Unkown message type '{json_data['status']}'")

                if "message" in json_data:
                    logger.warning(f"Management: Client {self.client.name} sends message: {json_data['message']}")

            except socket.timeout:
                continue
            except Exception as ex:
                logger.opt(exception=ex).error(f"Management: Client error: {self.addr}")
                break
        
        if self.client is not None:
            logger.info(f"Management: Client {self.client.name}@{self.addr}: Connection closed.")
            self.client.disconnect()
        else:
            logger.info(f"Management: Client {self.addr}: Connection closed.")

        self.client_socket.close()

    def stop(self):
        self.stop_event.set()

    def send_message(self, message: bytes):
        if len(message) > ManagementClientConnection.__MAX_FRAME_LEN:
            raise Exception("Message is too long!")
        
        self.client_socket.sendall(message + b'\n')

class ManagementServer(Dismantable):
    def __init__(self, bind_address, state_manager: state_manager.MachineStateManager):
        self.bind_address = bind_address
        self.client_threads = []
        self.keep_running = threading.Event()
        self.manager = state_manager
        self.is_started = False

    def _accept_connections(self):
        while True:
            try:
                client_socket, address = self.socket.accept()
                if self.keep_running.is_set():
                    break

                try:
                    client_connection = ManagementClientConnection(address, client_socket, self.manager)
                    client_connection.start()
                    self.client_threads.append(client_connection)
                except Exception as ex:
                    logger.opt(exception=ex).error(f"Management: Unable to accept client {address}")
            except socket.timeout:
                pass
        
        logger.debug(f"Management: Server shutting down")

    def start(self):
        self.keep_running.clear()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(self.bind_address)
        self.socket.listen(4)

        self.accept_thread = threading.Thread(target=self._accept_connections, daemon=True)
        self.accept_thread.start()
        logger.debug(f"Management: Server listing at {self.bind_address}")
        self.is_started = True

    def stop(self):
        self.keep_running.set()
        try:
            poison_pill = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            poison_pill.connect(self.bind_address)
            poison_pill.close()
        except Exception:
            pass

        for client in self.client_threads:
            client.stop()
        for client in self.client_threads:
            client.join()

        self.accept_thread.join()
        self.socket.close()
        self.is_started = False

    def dismantle(self) -> None:
        self.stop()

    def get_name(self) -> str:
        return "ManagementServer"
    
    def is_started(self) -> bool:
        return self.is_started()
