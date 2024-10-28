import time
import signal
import psutil
import traceback

from multiprocessing import Process, Manager
from threading import Event, Thread, Barrier

from common.application_configs import Applications, ApplicationConfig
from common.instance_manager_message import InstanceStatus

from management_client import ManagementClient, DownstreamMassage
from application_interface import ApplicationInterface

from applications.base_application import BaseApplication
from applications.iperf_client_application import IperfClientApplication
from applications.iperf_server_application import IperfServerApplication
from applications.ping_application import PingApplication
from applications.procmon_application import ProcmonApplication
from applications.run_program_application import RunProgramApplication

IM_SOCKET_PATH = "/tmp/im.sock"

class ApplicationController(Thread):
    @staticmethod
    def map_application(application: Applications) -> BaseApplication:
        match application:
            case Applications.IPERF3_SERVER:
                return IperfServerApplication()
            case Applications.IPERF3_CLIENT:
                return IperfClientApplication()
            case Applications.PING:
                return PingApplication()
            case Applications.PROCMON:
                return ProcmonApplication()
            case Applications.RUN_PROGRAM:
                return RunProgramApplication()
            case _:
                raise Exception(f"Unmapped application {application}")
            
    def __init__(self, config: ApplicationConfig, client: ManagementClient,
                 start_barrier: Barrier, instance_name: str) -> None:
        super(ApplicationController, self).__init__()
        self.config = config
        self.application: BaseApplication = ApplicationController.map_application(config.application)
        self.mgmt_client: ManagementClient = client
        self.settings = config.settings
        self.barrier: Barrier = start_barrier
        self.is_terminated = Event()
        self.manager = Manager()
        self.shared_state = self.manager.dict()
        self.instance_name = instance_name
        self.shared_state["error_flag"] = False
        self.shared_state["error_string"] = None

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
            except Exception as ex:
                raise "Unable to connect to Instance Manager Daemon" from ex
            rc = self.application.start_collection(self.settings, self.config.runtime, interface)

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
        
        time.sleep(self.config.delay)

        process.start()
        process.join(self.application.get_runtime_upper_bound(self.config.runtime) + 1)

        if process.is_alive():
            message = DownstreamMassage(InstanceStatus.MSG_ERROR, 
                                        f"Application {self.config.name} still runs after timeout.")
            self.mgmt_client.send_to_server(message)
            try:
                parent = psutil.Process(process.ident)
                for child in parent.children(recursive=True):
                    try: child.send_signal(signal.SIGTERM)
                    except Exception as ex:
                        message = DownstreamMassage(InstanceStatus.MSG_ERROR, 
                                                    f"Application {self.config.name}:\n Unable to kill childs: {ex}")
                        self.mgmt_client.send_to_server(message)
                        continue
            except Exception as ex:
                message = DownstreamMassage(InstanceStatus.MSG_ERROR, 
                                            f"Application {self.config.name}:\n Unable get childs: {ex}")
                self.mgmt_client.send_to_server(message)
                pass

            process.terminate()
            
        process.join()
        
        if not self.shared_state["error_flag"]:
            message = DownstreamMassage(InstanceStatus.MSG_SUCCESS, 
                                        f"Application {self.config.name} finished")
            self.mgmt_client.send_to_server(message)
        else:
            message = DownstreamMassage(InstanceStatus.MSG_ERROR, 
                                        f"Application {self.config.name} reported error: \n{self.shared_state['error_string']}")
            self.mgmt_client.send_to_server(message)
        
        self.is_terminated.set()

    def has_terminated(self) -> bool:
        return self.is_terminated.is_set()
    
    def error_occured(self) -> bool:
        return self.shared_state["error_flag"]
    
    def get_application_name(self) -> str:
        return self.config.name
