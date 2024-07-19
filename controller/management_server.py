import socket
import threading
import time
import json

from loguru import logger
from enum import Enum

from utils.interfaces import Dismantable
from utils.config_store import ConfigStore

class AgentManagementState(Enum):
    UNKNOWN = 0
    STARTED = 1
    INSTALLED = 2
    IN_EXPERIMENT = 3
    FINISHED = 4
    DISMANTLE = 5


class ManagementConnectionManager():
    def __init__(self):
        self.map = {}
    
    def add_connection(self, name, addr, connection):
        if name in self.map:
            logger.warning(f"Management: {name} was already registered!")
        
        self.map[name] = {
            "addr": addr, 
            "connection": connection, 
            "state": AgentManagementState.UNKNOWN
        }
        logger.info(f"Management: Client {name} was registered!")
    
    def remove_connection(self, name):
        if not name in self.map:
            return
        self.map.pop(name)
        logger.info(f"Management: Client {name} was unregistered!")
    
    def change_state(self, name: str, state: AgentManagementState):
        if name not in self.map:
            logger.warning(f"Management: {name} was not registered!")
            return
        
        self.map[name]["state"] = state
        logger.info(f"Management: Client {name} changed state to {state}")

    def get_agent_state(self, name: str) -> AgentManagementState:
        if name not in self.map:
            return AgentManagementState.UNKNOWN
        
        return self.map[name]["state"]
    
    def get_agent_remote_addr(self, name: str) -> str | None:
        if name not in self.map:
            return None
        
        return self.map[name]["addr"][0]
    
    def send_agent_message(self, name: str, message: bytes):
        if name not in self.map:
            raise Exception(f"Agent {name} was not registered!")
        
        self.map[name]["connection"].send_message(message)


class ManagementClientConnection(threading.Thread):
    __MAX_FRAME_LEN = 8192

    def __init__(self, addr, client_socket: socket, manager: ManagementConnectionManager):
        threading.Thread.__init__(self)
        self.addr = addr
        self.client_socket = client_socket
        self.manager = manager
        self.daemon = True
        self.connected_instance = None
        self.stop_event = threading.Event()
        self.client_name = None

    def run(self):
        logger.debug(f"Management: Client connected: {self.addr}")
        self.client_socket.settimeout(0.5)
        while not self.stop_event.is_set():
            try:
                data = self.client_socket.recv(ManagementClientConnection.__MAX_FRAME_LEN)
                if len(data) == 0:
                    logger.debug(f"Management: Client disconnected: {self.addr}")
                    break

                try:
                    json_data = json.loads(data.decode("utf-8"))
                except Exception as ex:
                    logger.opt(exception=ex).error(f"Management: Client JSON decoce error {self.addr}")
                
                # TODO: Parse.
                self.name = data.decode("utf-8").strip()
                self.manager.add_connection(self.name, self.addr, self)
                self.manager.change_state(self.name, AgentManagementState.STARTED)

            except socket.timeout:
                continue
            except Exception as ex:
                logger.opt(exception=ex).error(f"Management: Client error: {self.addr}")
                break
        if self.name is not None:
            self.manager.remove_connection(self.name)

    def stop(self):
        self.stop_event.set()

    def send_message(self, message: bytes):
        if len(bytes) > ManagementClientConnection.__MAX_FRAME_LEN:
            raise Exception("Message is too long!")
        
        self.client_socket.sendall(message)

class ManagementServer(Dismantable):
    def __init__(self, bind_address, config_store: ConfigStore):
        self.bind_address = bind_address
        self.config_store = config_store
        self.client_threads = []
        self.keep_running = threading.Event()
        self.manager = ManagementConnectionManager()
        self.is_started = False

    def _accept_connections(self):
        while True:
            try:
                client_socket, address = self.socket.accept()
                if self.keep_running.is_set():
                    break
                client_connection = ManagementClientConnection(address, client_socket, self.manager)
                client_connection.start()
                self.client_threads.append(client_connection)
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

    def get_manager(self) -> ManagementConnectionManager:
        return self.manager

if __name__ == "__main__":
    m = ManagementServer("127.0.0.1", 8080)
    m.start()
    time.sleep(20)
    print(m.get_manager().get_agent_state("test"))
    m.get_manager().send_agent_message("test", "Test".encode("utf-8"))
    time.sleep(20)
    m.stop()
    while m.is_started():
        pass
