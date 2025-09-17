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

import time
import signal
import psutil
import traceback
import time

from multiprocessing import Process, Manager
from multiprocessing import Event as MultiprocessingEvent
from threading import Event, Thread
from typing import cast, Optional

from common.application_configs import ApplicationConfig, AppStartStatus
from common.instance_manager_message import LogMessageType
from management_client import ManagementClient
from application_interface import ApplicationInterface
from applications.base_application import BaseApplication
from applications.generic_application_interface import GenericApplicationInterface
from global_state import GlobalState


class ApplicationController(Thread):
            
    def __init__(self, app: BaseApplication, config: ApplicationConfig, 
                 client: ManagementClient, instance_name: str,
                 application_manager) -> None:
        super(ApplicationController, self).__init__()
        self.config: ApplicationConfig = config
        self.app: BaseApplication = app
        self.mgmt_client: ManagementClient = client
        self.application_manager = application_manager
        self.settings = config.settings
        self.is_terminated = Event()
        self.manager = Manager()
        self.shared_state = self.manager.dict()
        self.started_event = MultiprocessingEvent()
        self.instance_name = instance_name
        self.shared_state["error_flag"] = False
        self.shared_state["error_string"] = None 
        self.t0: Optional[float] = None
        self.start_defered: bool = False
        self.daemon = True

    def __del__(self) -> None:
        del self.app
        del self.config

    def __fork_run(self):
        """
        Important: This method will be forked away from main instance_manager
        process. In order to communicate back to the main process, the
        shared_state has to be used! Only the main process has a connection
        to the management server!
        """

        try:
            try:
                interface = ApplicationInterface(self.config.name, 
                                                 GlobalState.im_daemon_socket_path,
                                                 self.started_event)
                interface.connect()
                self.app.attach_interface(cast(GenericApplicationInterface, interface))
            except Exception as ex:
                raise "Unable to connect to Instance Manager Daemon" from ex
            
            self.app.report_startup()
            rc = self.app.start(self.config.runtime)

            interface.disconnect()
            if not rc:
                self.shared_state["error_flag"] = True
                self.shared_state["error_string"] = f"Application finished with return code: {rc}"
        except Exception as ex:
            traceback.print_exception(ex)
            self.shared_state["error_flag"] = True
            self.shared_state["error_string"] = str(ex)

    def update_t0(self, t0: float) -> None:
        self.t0 = t0

    def run(self):
        self.started_event.clear()
        process = Process(target=self.__fork_run, args=())
        # Python >= 3.11 used nanosleep, which is quite accurate
        if self.t0 is None:
            wait_for = self.config.delay
        else:
            wait_for = (self.t0 - time.time()) + self.config.delay

        time.sleep(wait_for)
        process.start()

        total_wait = 10
        if self.config.runtime is not None:
            total_wait += self.app.get_runtime_upper_bound(self.config.runtime)
            wait_for_init = time.time()

        if not self.started_event.wait(total_wait):
            self.mgmt_client.send_extended_app_log(f"Application has not reported start event!", 
                                               LogMessageType.MSG_ERROR, 
                                               True)
        
        self.application_manager.report_app_status(self, AppStartStatus.START)
        wait_left = None

        if self.config.runtime is not None:
            wait_left = max(0, total_wait - (time.time() - wait_for_init))

        # If no runtime is specified, the Application is a daemon process. 
        # It will remain running in background, but the testbed execution is not delayed by this Application
        if self.config.runtime is not None:
            process.join(wait_left)

            if process.is_alive():
                self.mgmt_client.send_extended_app_log(f"Application still runs after timeout.", 
                                                   LogMessageType.MSG_ERROR, 
                                                   True)
                try:
                    parent = psutil.Process(process.ident)
                    for child in parent.children(recursive=True):
                        try: child.send_signal(signal.SIGTERM)
                        except Exception as ex:
                            self.mgmt_client.send_extended_app_log(f"Application is unable to kill children: {ex}", 
                                                               LogMessageType.MSG_ERROR, 
                                                               True)
                            continue
                except Exception as ex:
                    self.mgmt_client.send_extended_app_log(f"Application is unable get children: {ex}", 
                                                       LogMessageType.MSG_ERROR, 
                                                       True)

                process.terminate()

            self.application_manager.report_app_status(self, AppStartStatus.FINISH)
            process.join()

        if not self.shared_state["error_flag"]:
            if self.config.runtime is None:
                self.mgmt_client.send_extended_app_log(f"Application started as daemon", 
                                                   LogMessageType.MSG_SUCCESS, 
                                                   True)
                self.application_manager.report_app_status(self, AppStartStatus.DAEMON)
            else:
                self.mgmt_client.send_extended_app_log(f"Application finished", 
                                                   LogMessageType.MSG_SUCCESS, 
                                                   True)
        else:
            self.mgmt_client.send_extended_app_log(f"Application reported error: \n{self.shared_state['error_string']}", 
                                                LogMessageType.MSG_SUCCESS, 
                                                True)
        
        self.is_terminated.set()

    def has_terminated(self) -> bool:
        return self.is_terminated.is_set()
    
    def error_occurred(self) -> bool:
        return self.shared_state["error_flag"]
    
    def get_application_name(self) -> str:
        return self.config.name
