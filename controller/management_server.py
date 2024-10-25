import socket
import threading
import json
import time

from loguru import logger
from jsonschema import validate
import os

from utils.interfaces import Dismantable
from utils.system_commands import get_asset_relative_to
from common.instance_manager_message import *
from utils.influxdb import InfluxDBAdapter

import state_manager

class ManagementClientConnection(threading.Thread):
    __MAX_FRAME_LEN = 8192

    message_schema = None

    def __init__(self, socket_path,  
                 manager: state_manager.MachineStateManager, 
                 instance: state_manager.MachineState,
                 influx_adapter: InfluxDBAdapter,
                 timeout: int):
        threading.Thread.__init__(self)
        self.socket_path = socket_path
        self.expected_instance = instance
        self.influx_adapter = influx_adapter
        self.manager = manager
        self.timeout = timeout
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
            logger.opt(exception=ex).error(f"Management: Client '{self.expected_instance.name}': message parsing error")
            return False
            

        message_obj = InstanceManagerDownstream(**json_data)

        if self.client is None:
            self.client = self.manager.get_machine(message_obj.name)
            if self.client is None:
                logger.error(f"Management: Client '{self.expected_instance.name}': reported invalid instance name: {message_obj.name}")
                return False
            self.client.connect(self)
        else:
            if self.client.name != message_obj.name:
                logger.error(f"Management: Client '{self.expected_instance.name}': reported name {self.client.name} before, now {message_obj.name}")
                return False

        match message_obj.get_status():
            case InstanceStatus.STARTED:
                previous = self.client.get_state()
                if previous == state_manager.AgentManagementState.DISCONNECTED:
                    logger.error(f"Management: Client '{self.expected_instance.name}': Restarted after it was in state {previous}. Instance Manager failed?")
                    self.client.set_state(state_manager.AgentManagementState.FAILED)
                elif previous == state_manager.AgentManagementState.INITIALIZED:
                    logger.warning(f"Management: Client '{self.expected_instance.name}': Restarted after it was in state {previous}. Skipping Instance setup!")
                    self.client.set_state(state_manager.AgentManagementState.INITIALIZED)
                else:
                    self.client.set_state(state_manager.AgentManagementState.STARTED)
                    logger.info(f"Management: Client '{self.expected_instance.name}': Started. Sending setup instructions.")
                    self.send_message(InitializeMessageUpstream(
                        "initialize", 
                        self.client.get_setup_env()[0], 
                        self.client.get_setup_env()[1]).to_json().encode("utf-8"))
            case InstanceStatus.INITIALIZED:
                self.client.set_state(state_manager.AgentManagementState.INITIALIZED)
                logger.info(f"Management: Client {self.client.name} initialized.")
            case InstanceStatus.MSG_ERROR | InstanceStatus.MSG_INFO | InstanceStatus.MSG_SUCCESS | InstanceStatus.DATA_POINT:
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
                logger.info(f"Management: Client {self.client.name} reported finished applications.")
            case _:
                logger.warning(f"Management: Client {self.client.name}: Unkown message type '{message_obj.status}'")

        if message_obj.message is not None:
            if message_obj.get_status() == InstanceStatus.DATA_POINT:
                if not self.influx_adapter.insert(message_obj.message):
                    logger.warning(f"Management: Client {self.client.name}: Unable to add reported point to InfluxDB")
                return True

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
        started_waiting = time.time()

        while True:
            if os.path.exists(self.socket_path):
                logger.debug(f"Management: Socket '{self.socket_path}' for Instance {self.expected_instance.name} ready")
                break

            if (started_waiting + self.timeout) < time.time():
                logger.error(f"Management: Client connection error: Socket '{self.socket_path}' does not exist after timeout!")
                return

        try:
            self.client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.client_socket.settimeout(0.5)
            self.client_socket.connect(str(self.socket_path))
            logger.debug(f"Management: Client '{self.expected_instance.name}': Socket connection created.")
        except Exception as ex:
            logger.opt(exception=ex).error(f"Management: Unable to bind socket for '{self.expected_instance.name}'")
            return

        partial_data = ""

        while not self.stop_event.is_set():
            try:
                data = self.client_socket.recv(ManagementClientConnection.__MAX_FRAME_LEN)
                if len(data) == 0:
                    logger.debug(f"Management: Client '{self.expected_instance.name}': Disconnected (0 bytes read)")
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
                logger.opt(exception=ex).error(f"Management: Client error: '{self.expected_instance.name}'")
                break
        
        if self.client is not None:
            logger.info(f"Management: Client '{self.client.name}': Connection closed.")
            self.client.disconnect()
        else:
            logger.info(f"Management: Client '{self.expected_instance.name}': Connection closed.")

        self.client_socket.close()

    def stop(self):
        self.stop_event.set()

    def send_message(self, message: bytes):
        self.client_socket.sendall(message + b'\n')

class ManagementServer(Dismantable):
    def __init__(self, state_manager: state_manager.MachineStateManager, startup_init_timeout: int, influx_adapter: InfluxDBAdapter):
        self.client_threads = []
        self.influx_adapter = influx_adapter
        self.keep_running = threading.Event()
        self.startup_init_timeout = startup_init_timeout
        self.manager = state_manager
        self.is_started = False

    def start(self):
        self.keep_running.clear()

        for instance in self.manager.get_all_machines():
            if not instance.interchange_ready:
                raise Exception(f"Interchange files of instance {instance.name} not ready!")

            try:
                client_connection = ManagementClientConnection(instance.get_mgmt_socket_path(), 
                                                               self.manager, 
                                                               instance, 
                                                               self.influx_adapter, 
                                                               self.startup_init_timeout)
                client_connection.start()
                self.client_threads.append(client_connection)
            except Exception as ex:
                logger.opt(exception=ex).error(f"Management: Unable to start client socket connection for {instance.name}")

        logger.info(f"Management: Client connection threads started.")
        self.is_started = True
        

    def stop(self):
        self.keep_running.set()

        for client in self.client_threads:
            client.stop()
        for client in self.client_threads:
            client.join()

        self.is_started = False

    def dismantle(self) -> None:
        self.stop()

    def get_name(self) -> str:
        return "ManagementServer"
    
    def is_started(self) -> bool:
        return self.is_started()
