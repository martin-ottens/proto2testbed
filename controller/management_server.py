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
import threading
import json
import time
import os
import errno
import jsonpickle

from loguru import logger
from pathlib import Path

from utils.interfaces import Dismantable
from common.instance_manager_message import *
from common.application_configs import AppStartStatus
from utils.influxdb import InfluxDBAdapter

import state_manager
from state_manager import AgentManagementState


class ManagementClientConnection(threading.Thread):
    __MAX_FRAME_LEN = 8192

    def __init__(self, controller,
                 manager: state_manager.InstanceStateManager, 
                 instance: state_manager.InstanceState,
                 influx_adapter: InfluxDBAdapter,
                 timeout: int,
                 init_instant: bool,
                 socket_path: Optional[Path] = None,
                 vsock_cid: Optional[int] = None):
        threading.Thread.__init__(self)
        self.socket_path = socket_path
        self.vsock_cid = vsock_cid
        self.controller = controller
        self.expected_instance = instance
        self.influx_adapter = influx_adapter
        self.manager = manager
        self.timeout = timeout
        self.init_instant = init_instant
        self.daemon = True
        self.stop_event = threading.Event()
        self.client = None
        self.connected = False
        self.client_socket = None

    @staticmethod
    def _message_type_to_logger(type: LogMessageType, message: str) -> None:
        match type:
            case LogMessageType.MSG_SUCCESS:
                logger.opt(ansi=True).success(message)
            case LogMessageType.MSG_INFO:
                logger.opt(ansi=True).info(message)
            case LogMessageType.MSG_DEBUG:
                logger.opt(ansi=True).debug(message)
            case LogMessageType.MSG_WARNING:
                logger.opt(ansi=True).warning(message)
            case LogMessageType.MSG_ERROR:
                logger.opt(ansi=True).error(message)
            case LogMessageType.STDERR:
                logger.opt(ansi=True).trace(f"STDERR: {message}")
            case LogMessageType.STDOUT:
                logger.opt(ansi=True).trace(f"STDOUT: {message}")

    def _process_one_message(self, data) -> bool:
        message_obj: Optional[InstanceManagerMessageDownstream] = None
        try:
            message_obj = jsonpickle.decode(data)
        except Exception as ex:
            logger.opt(exception=ex).error(f"Management: Client '{self.expected_instance.name}': message parsing error")
            return False

        if self.client is None:
            self.client = self.manager.get_instance(message_obj.name)
            if self.client is None:
                logger.error(f"Management: Client '{self.expected_instance.name}': reported invalid instance name: {message_obj.name}")
                return False
            self.client.connect(self)
        else:
            if self.client.name != message_obj.name:
                logger.error(f"Management: Client '{self.expected_instance.name}': reported name {self.client.name} before, now {message_obj.name}")
                return False

        # Handle state transition messages
        match message_obj.status:
            case InstanceMessageType.STARTED:
                previous = self.client.get_state()
                if previous == AgentManagementState.DISCONNECTED:
                    logger.error(f"Management: Client '{self.expected_instance.name}': Restarted after it was in state {previous}. Instance Manager failed?")
                    self.client.set_state(AgentManagementState.FAILED)
                    self.send_message(InitializeMessageUpstream(None, None))

                elif previous == AgentManagementState.INITIALIZED:
                    logger.warning(f"Management: Client '{self.expected_instance.name}': Restarted after it was in state {previous}. Skipping Instance setup!")
                    self.client.set_state(AgentManagementState.INITIALIZED)
                    self.send_message(InitializeMessageUpstream(None, None))

                elif previous == AgentManagementState.APPS_READY or previous == AgentManagementState.APPS_SENDED:
                    logger.warning(f"Management: Client '{self.expected_instance.name}': Restarted after it was in state {previous}. Re-Installing apps!")
                    self.client.set_state(AgentManagementState.INITIALIZED)
                    self.send_message(InstallApplicationsMessageUpstream(self.expected_instance.apps))
                
                else:
                    self.client.set_state(AgentManagementState.STARTED)
                    if self.init_instant:
                        logger.info(f"Management: Client '{self.expected_instance.name}': Started. Sending setup instructions for instant setup.")
                        self.send_message(InitializeMessageUpstream(
                            self.client.get_setup_env()[0], 
                            self.client.get_setup_env()[1]))
                    else:
                        logger.info(f"Management: Client '{self.expected_instance.name}': Started. Setup deferred.")
            case InstanceMessageType.INITIALIZED:
                self.client.set_state(AgentManagementState.INITIALIZED)
                logger.info(f"Management: Client {self.client.name} initialized.")

            case InstanceMessageType.FAILED | InstanceMessageType.APPS_FAILED:
                self.client.set_state(AgentManagementState.FAILED)
                if message_obj.payload is not None:
                    logger.error(f"Management: Client {self.client.name} reported failure with message: {message_obj.payload}")
                    self.manager.provider.result_wrapper.append_instance_log(instance=self.client.name,
                                                                             message=f"Instance failed: {message_obj.payload}",
                                                                             type=LogMessageType.MSG_ERROR)
                else:
                    logger.error(f"Management: Client {self.client.name} reported failure without message.")
                return True
                
            case InstanceMessageType.APPS_INSTALLED:
                self.client.set_state(AgentManagementState.APPS_READY)
                logger.info(f"Management: Client {self.client.name} installed apps, ready for experiment.")
                return True

            case InstanceMessageType.APPS_DONE:
                self.client.set_state(AgentManagementState.FINISHED)
                logger.info(f"Management: Client {self.client.name} completed its applications.")
                return True

            case InstanceMessageType.FINISHED:
                self.client.set_state(AgentManagementState.FILES_PRESERVED)
                logger.info(f"Management: Client {self.client.name} is ready for shut down.")
                return True
            
            case InstanceMessageType.COPIED_FILE:
                self.client.file_copy_helper.feedback_from_instance(message_obj.payload)
                return True
            
            case InstanceMessageType.SHUTDOWN:
                logger.warning(f"Management: Client {self.client.name} requested testbed shutdown.")
                restart = (message_obj.payload is not None and bool(message_obj.payload) == True)
                self.manager.apply_shutdown_signal()
                self.controller.stop_interaction(restart=restart)
                return True
            
            case InstanceMessageType.DATA_POINT | InstanceMessageType.APPS_EXTENDED_STATUS | InstanceMessageType.SYSTEM_EXTENDED_LOG:
                # Just payload depended messages
                pass
            
            case _:
                logger.warning(f"Management: Client {self.client.name}: Unknown message type '{message_obj.status}'")

        # Handle payload dependend messages
        if message_obj.payload is not None:
            if message_obj.status == InstanceMessageType.DATA_POINT:
                if not self.influx_adapter.insert(message_obj.payload):
                    logger.warning(f"Management: Client {self.client.name}: Unable to add reported point to InfluxDB")
                return True
            
            if message_obj.status == InstanceMessageType.SYSTEM_EXTENDED_LOG:
                if not isinstance(message_obj.payload, ExtendedLogMessage):
                    logger.warning(f"Management: Got invalid payload type for instance log message from client {self.client.name}.")
                    return True
                
                extended_log: ExtendedLogMessage = message_obj.payload
                
                if extended_log.print_to_user:
                    ManagementClientConnection._message_type_to_logger(extended_log.log_message_type, 
                                                                       f"<y>[Instance {self.client.name}]</y> {extended_log.message}")
                
                if self.manager.provider.result_wrapper is not None and extended_log.store_in_log:
                    self.manager.provider.result_wrapper.append_instance_log(instance=self.client.name,
                                                                             message=extended_log.message,
                                                                             type=extended_log.log_message_type)
                return True
            
            if message_obj.status == InstanceMessageType.APPS_EXTENDED_STATUS:
                if not isinstance(message_obj.payload, ExtendedApplicationMessage):
                    logger.warning(f"Management: Got invalid payload type for application log message from client {self.client.name}")
                    return True
                
                application_log: ExtendedApplicationMessage = message_obj.payload

                if application_log.print_to_user:
                    ManagementClientConnection._message_type_to_logger(application_log.log_message_type,
                                                                       f"<y>[Application {application_log.application} from {self.client.name}]</y> {application_log.log_message}")

                if self.manager.provider.result_wrapper is not None and application_log.store_in_log:
                    self.manager.provider.result_wrapper.append_application_log(instance=self.client.name,
                                                                                application=application_log.application,
                                                                                message=application_log.log_message,
                                                                                type=application_log.log_message_type)

                if application_log.status != ApplicationStatus.UNCHANGED:
                    if self.manager.provider.result_wrapper is not None:
                        logger.trace(f"Application {application_log.application}@{self.client.name} changed its state to {application_log.status}")
                        self.manager.provider.result_wrapper.change_status(instance=self.client.name,
                                                                           application=application_log.application,
                                                                           new_status=application_log.status)

                    if application_log.status == ApplicationStatus.EXECUTION_STARTED:
                        self.manager.report_app_state_change(self.client.name, application_log.application, AppStartStatus.START)
                    elif application_log.status == ApplicationStatus.EXECUTION_FINISHED:
                        self.manager.report_app_state_change(self.client.name, application_log.application, AppStartStatus.FINISH)
                        
                
                return True

            match message_obj.status:
                case InstanceMessageType.MSG_INFO:
                    fn = logger.info
                case InstanceMessageType.MSG_ERROR:
                    fn = logger.error
                case InstanceMessageType.MSG_SUCCESS:
                    fn = logger.success
                case InstanceMessageType.MSG_DEBUG:
                    fn = logger.debug
                case _:
                    fn = logger.warning
            
            fn(f"LOG - Instance {self.client.name}: {message_obj.payload}")
        
        return True
    
    def _check_if_valid_json(self, json_str: str) -> bool:
        try:
            json.loads(json_str)
            return True
        except Exception as _:
            return False

    def run(self):
        if self.vsock_cid is None and self.socket_path is None:
            logger.critical("Management: Unable to connect: No VSOCK CID or Management Socket Path defined.")
            return

        if self.socket_path:
            started_waiting = time.time()
            while True:
                if os.path.exists(self.socket_path):
                    logger.debug(f"Management: Socket '{self.socket_path}' for Instance {self.expected_instance.name} ready")
                    break

                if ((started_waiting + self.timeout) < time.time()) or self.stop_event.is_set():
                    logger.error(f"Management: Client connection error: Socket '{self.socket_path}' does not exist after timeout or waiting was interrupted!")
                    return

            try:
                self.client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.client_socket.settimeout(0.5)
                self.client_socket.connect(str(self.socket_path))
                logger.debug(f"Management: Client '{self.expected_instance.name}': Socket connection created.")
            except Exception as ex:
                logger.opt(exception=ex).error(f"Management: Unable to bind socket for '{self.expected_instance.name}'")
                return
        else:
            started_waiting = time.time()
            while True:
                if ((started_waiting + self.timeout) < time.time()) or self.stop_event.is_set():
                    logger.error(f"Management: Client connection error: VSOCK with CID '{self.vsock_cid}' does not exist after timeout or waiting was interrupted!")
                    return

                try:
                    self.client_socket = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
                    self.client_socket.settimeout(0.1)
                    self.client_socket.connect((self.vsock_cid, 424242))
                    logger.debug(f"Management: Client '{self.expected_instance.name}': VSOCK connection established.")
                    break
                except socket.timeout:
                    logger.trace(f"Management: VSOCK for Instance '{self.expected_instance.name}' is not ready yet (timeout)")
                    sleep = 2
                except OSError as ex:
                    if ex.errno == errno.ENODEV:
                        logger.trace(f"Management: VSOCK for Instance '{self.expected_instance.name}' is not ready yet (ENODEV)")
                        sleep = 2
                    else:
                        sleep = 0.1
                except Exception as ex:
                    logger.opt(exception=ex).trace(f"Management: VSOCK exists for '{self.expected_instance.name}', but client not yet available.")
                    sleep = 0.1
                
                time.sleep(sleep)

        self.connected = True
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

    def send_message(self, message: UpstreamMessage) -> bool:
        if not self.connected:
            return False
        else:
            self.client_socket.sendall(message.as_json() + b'\n')
            return True

class ManagementServer(Dismantable):
    def __init__(self, controller, 
                 state_manager: state_manager.InstanceStateManager, 
                 startup_init_timeout: int, 
                 influx_adapter: InfluxDBAdapter, 
                 init_instant: bool = False):
        self.controller = controller
        self.client_threads = []
        self.influx_adapter = influx_adapter
        self.keep_running = threading.Event()
        self.startup_init_timeout = startup_init_timeout
        self.manager = state_manager
        self.init_instant = init_instant
        self.is_started = False

    def start(self):
        self.keep_running.clear()

        for instance in self.manager.get_all_instances():
            if not instance.interchange_ready:
                raise Exception(f"Interchange files of instance {instance.name} not ready!")

            try:
                client_connection = ManagementClientConnection(controller=self.controller,
                                                               manager=self.manager, 
                                                               instance=instance, 
                                                               influx_adapter=self.influx_adapter, 
                                                               timeout=self.startup_init_timeout,
                                                               init_instant=self.init_instant,
                                                               socket_path=instance.get_mgmt_socket_path(),
                                                               vsock_cid=instance.get_vsock_cid())
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

    def dismantle(self, force: bool = False) -> None:
        self.stop()

    def get_name(self) -> str:
        return "ManagementServer"
    
    def is_started(self) -> bool:
        return self.is_started
