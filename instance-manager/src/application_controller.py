import time
import signal
import psutil
import traceback

from multiprocessing import Process, Manager
from threading import Event, Thread, Barrier

from common.application_configs import ApplicationConfig
from common.instance_manager_message import InstanceMessageType

from management_client import ManagementClient, DownstreamMassage
from application_interface import ApplicationInterface

from base_application import BaseApplication

IM_SOCKET_PATH = "/tmp/im.sock"

class ApplicationController(Thread):
            
    def __init__(self, app: BaseApplication, config: ApplicationConfig, 
                 client: ManagementClient, start_barrier: Barrier, 
                 instance_name: str) -> None:
        super(ApplicationController, self).__init__()
        self.config: ApplicationConfig = config
        self.app: BaseApplication = app
        self.mgmt_client: ManagementClient = client
        self.settings = config.settings
        self.barrier: Barrier = start_barrier
        self.is_terminated = Event()
        self.manager = Manager()
        self.shared_state = self.manager.dict()
        self.instance_name = instance_name
        self.shared_state["error_flag"] = False
        self.shared_state["error_string"] = None

    def __del__(self) -> None:
        del self.app
        del self.config

    def __fork_run(self):
        """
        Important: This method will be forked away from main instance_manager
        process. In order to communicate back to the main process, the
        shared_state has to be used! Only the main process has a connection to
        to the management server!
        """

        try:
            try:
                interface = ApplicationInterface(self.config.name, IM_SOCKET_PATH)
                interface.connect()
                self.app.attach_interface(interface)
            except Exception as ex:
                raise "Unable to connect to Instance Manager Daemon" from ex
            
            rc = self.app.start(self.config.runtime)

            interface.disconnect()
            if not rc:
                self.shared_state["error_flag"] = True
                self.shared_state["error_string"] = f"Application finished with return code: {rc}"
        except Exception as ex:
            traceback.print_exception(ex)
            self.shared_state["error_flag"] = True
            self.shared_state["error_string"] = str(ex)

    def run(self):
        process = Process(target=self.__fork_run, args=())
        
        self.barrier.wait()

        print(f"{self.config.name} timeout: {self.app.get_runtime_upper_bound(self.config.runtime)}/{self.config.runtime}", flush=True)        
        time.sleep(self.config.delay)
        process.start()
        process.join(self.app.get_runtime_upper_bound(self.config.runtime) + 10)

        if process.is_alive():
            message = DownstreamMassage(InstanceMessageType.MSG_ERROR, 
                                        f"Application {self.config.name} still runs after timeout.")
            self.mgmt_client.send_to_server(message)
            try:
                parent = psutil.Process(process.ident)
                for child in parent.children(recursive=True):
                    try: child.send_signal(signal.SIGTERM)
                    except Exception as ex:
                        message = DownstreamMassage(InstanceMessageType.MSG_ERROR, 
                                                    f"Application {self.config.name}:\n Unable to kill childs: {ex}")
                        self.mgmt_client.send_to_server(message)
                        continue
            except Exception as ex:
                message = DownstreamMassage(InstanceMessageType.MSG_ERROR, 
                                            f"Application {self.config.name}:\n Unable get childs: {ex}")
                self.mgmt_client.send_to_server(message)
                pass

            process.terminate()
            
        process.join()
        
        if not self.shared_state["error_flag"]:
            message = DownstreamMassage(InstanceMessageType.MSG_SUCCESS, 
                                        f"Application {self.config.name} finished")
            self.mgmt_client.send_to_server(message)
        else:
            message = DownstreamMassage(InstanceMessageType.MSG_ERROR, 
                                        f"Application {self.config.name} reported error: \n{self.shared_state['error_string']}")
            self.mgmt_client.send_to_server(message)
        
        self.is_terminated.set()

    def has_terminated(self) -> bool:
        return self.is_terminated.is_set()
    
    def error_occured(self) -> bool:
        return self.shared_state["error_flag"]
    
    def get_application_name(self) -> str:
        return self.config.name
