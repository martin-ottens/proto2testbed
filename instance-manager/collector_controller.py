import time
import signal
import psutil
import traceback

from multiprocessing import Process, Manager
from threading import Event, Thread, Barrier

from common.collector_configs import Collectors, ExperimentConfig
from common.instance_manager_message import InstanceStatus
from common.configs import InfluxDBConfig

from management_client import ManagementClient, DownstreamMassage

from data_collectors.influxdb_adapter import InfluxDBAdapter
from data_collectors.base_collector import BaseCollector
from data_collectors.iperf_client_collector import IperfClientCollector
from data_collectors.iperf_server_collector import IperfServerCollector
from data_collectors.ping_collector import PingCollector
from data_collectors.procmon_collector import ProcmonCollector

class CollectorController(Thread):
    @staticmethod
    def map_collector(collector: Collectors) -> BaseCollector:
        match collector:
            case Collectors.IPERF3_SERVER:
                return IperfServerCollector()
            case Collectors.IPERF3_CLIENT:
                return IperfClientCollector()
            case Collectors.PING:
                return PingCollector()
            case Collectors.PROCMON:
                return ProcmonCollector()
            case _:
                raise Exception(f"Unmapped Collector {collector}")
            
    def __init__(self, config: ExperimentConfig, client: ManagementClient,
                 start_barrier: Barrier, influx_config: InfluxDBConfig, 
                 instance_name: str) -> None:
        super(CollectorController, self).__init__()
        self.config = config
        self.collector: BaseCollector = CollectorController.map_collector(config.collector)
        self.mgmt_client: ManagementClient = client
        self.settings = config.settings
        self.barrier: Barrier = start_barrier
        self.is_terminated = Event()
        self.manager = Manager()
        self.shared_state = self.manager.dict()
        self.instance_name = instance_name
        self.shared_state["error_flag"] = False
        self.shared_state["error_string"] = None

        self.influx_config: InfluxDBConfig = influx_config

    def __fork_run(self):
        """
        Important: This method will be forked away from main instance_manager
        process. In order to communicate back to the main process, the
        shared_state has to be used! Only the main process has a connection to
        to the management server!
        """

        try:
            local_influx_adapter = InfluxDBAdapter(self.influx_config, self.get_experiment_name(), self.instance_name)
            rc = self.collector.start_collection(self.settings, self.config.runtime, local_influx_adapter)
            if not rc:
                self.shared_state["error_flag"] = True
                self.shared_state["error_string"] = f"Collector finished with return code: {rc}"
        except Exception as ex:
            traceback.print_exception(ex)
            self.shared_state["error_flag"] = True
            self.shared_state["error_string"] = str(ex)
        finally:
            local_influx_adapter.close()

    def run(self):
        process = Process(target=self.__fork_run, args=())
        
        self.barrier.wait()
        
        time.sleep(self.config.delay)

        process.start()
        process.join(self.collector.get_runtime_upper_bound(self.config.runtime) + 1)

        if process.is_alive():
            message = DownstreamMassage(InstanceStatus.MSG_ERROR, 
                                        f"Experiment {self.config.name} still runs after timeout.")
            self.mgmt_client.send_to_server(message)
            try:
                parent = psutil.Process(process.ident)
                for child in parent.children(recursive=True):
                    try: child.send_signal(signal.SIGTERM)
                    except Exception as ex:
                        message = DownstreamMassage(InstanceStatus.MSG_ERROR, 
                                                    f"Experiment {self.config.name}:\n Unable to kill childs: {ex}")
                        self.mgmt_client.send_to_server(message)
                        continue
            except Exception as ex:
                message = DownstreamMassage(InstanceStatus.MSG_ERROR, 
                                            f"Experiment {self.config.name}:\n Unable get childs: {ex}")
                self.mgmt_client.send_to_server(message)
                pass

            process.terminate()
            
        process.join()
        
        if not self.shared_state["error_flag"]:
            message = DownstreamMassage(InstanceStatus.MSG_SUCCESS, 
                                        f"Experiment {self.config.name} finished")
            self.mgmt_client.send_to_server(message)
        else:
            message = DownstreamMassage(InstanceStatus.MSG_ERROR, 
                                        f"Experiment {self.config.name} reported error: \n{self.shared_state['error_string']}")
            self.mgmt_client.send_to_server(message)
        
        self.is_terminated.set()

    def has_terminated(self) -> bool:
        return self.is_terminated.is_set()
    
    def error_occured(self) -> bool:
        return self.shared_state["error_flag"]
    
    def get_experiment_name(self) -> str:
        return self.config.name
