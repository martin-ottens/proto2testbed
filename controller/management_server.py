import socket
import threading
import json

from loguru import logger
from jsonschema import validate
from pathlib import Path

from utils.interfaces import Dismantable
from utils.system_commands import get_asset_relative_to
from common.instance_manager_message import *

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
            with open(get_asset_relative_to(__file__, "assets/statusmsg.schema.json"), "r") as handle:
                ManagementClientConnection.message_schema = json.load(handle)

    def _process_one_message(self, data) -> bool:
        try:
            json_data = json.loads(data)
            validate(schema=ManagementClientConnection.message_schema, instance=json_data)
        except Exception as ex:
            logger.opt(exception=ex).error(f"Management: Client {self.addr} message parsing error")
            return False
            

        message_obj = InstanceManagerDownstream(**json_data)

        if self.client is None:
            self.client = self.manager.get_machine(message_obj.name)
            if self.client is None:
                logger.error(f"Management: Client {self.addr} reported invalid instance name: {message_obj.name}")
                return False
            self.client.connect(self.addr, self)
        else:
            if self.client.name != message_obj.name:
                logger.error(f"Management: Client {self.addr} reported name {self.client.name} before, now {message_obj.name}")
                return False

        match message_obj.get_status():
            case InstanceStatus.STARTED:
                self.client.set_state(state_manager.AgentManagementState.STARTED)
                logger.info(f"Management: Client {self.client.name} started. Sending setup instructions.")
                self.send_message(InitializeMessageUpstream(
                    "initialize", 
                    self.client.get_setup_env()[0], 
                    self.client.get_setup_env()[1]).to_json().encode("utf-8"))
            case InstanceStatus.INITIALIZED:
                self.client.set_state(state_manager.AgentManagementState.INITIALIZED)
                logger.info(f"Management: Client {self.client.name} initialized.")
            case InstanceStatus.MSG_ERROR | InstanceStatus.MSG_INFO | InstanceStatus.MSG_SUCCESS:
                pass
            case InstanceStatus.FAILED | InstanceStatus.EXPERIMENT_FAILED:
                self.client.set_state(state_manager.AgentManagementState.FAILED)
                if message_obj.message is not None:
                    logger.error(f"Management: Client {self.client.name} reported failure with message: {message_obj.message}")
                else:
                    logger.error(f"Management: Client {self.client.name} reported failure without message.")
                if message_obj.get_status() == InstanceStatus.FAILED:
                    return False
                else:
                    return True
            case InstanceStatus.EXPERIMENT_DONE:
                self.client.set_state(state_manager.AgentManagementState.FINISHED)
                logger.info(f"Management: Client {self.client.name} reported finished experiments.")
            case _:
                logger.warning(f"Management: Client {self.client.name}: Unkown message type '{message_obj.status}'")

        if message_obj.message is not None:
            match message_obj.get_status():
                case InstanceStatus.MSG_INFO:
                    fn = logger.info
                case InstanceStatus.MSG_ERROR:
                    fn = logger.error
                case InstanceStatus.MSG_SUCCESS:
                    fn = logger.success
                case _:
                    fn = logger.warning
            
            fn(f"Management: Client {self.client.name} sends message: {message_obj.message}")
        
        return True
    
    def _check_if_valid_json(self, str) -> bool:
        try:
            json.loads(str)
            return True
        except Exception as _:
            return False

    def run(self):
        logger.info(f"Management: Client {self.addr} connected")
        self.client_socket.settimeout(0.5)

        partial_data = ""

        while not self.stop_event.is_set():
            try:
                data = self.client_socket.recv(ManagementClientConnection.__MAX_FRAME_LEN)
                if len(data) == 0:
                    logger.debug(f"Management: Client {self.addr} disconnected (0 bytes read)")
                    break

                partial_data = partial_data + data.decode("utf-8")

                if "}\n{" in partial_data:
                    # Multipart message
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
                    # Singlepart message
                    if self._check_if_valid_json(partial_data):
                        if not self._process_one_message(partial_data):
                            break
                        partial_data = ""

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
                client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
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
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.socket.bind(self.bind_address)
        self.socket.listen(4)

        self.accept_thread = threading.Thread(target=self._accept_connections, daemon=True)
        self.accept_thread.start()
        logger.info(f"Management: Server listing at {self.bind_address}")
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
