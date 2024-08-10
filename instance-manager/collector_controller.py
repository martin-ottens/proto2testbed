import time
import signal
import psutil

from multiprocessing import Process, Manager
from threading import Event, Thread

from common.collector_configs import Collectors, ExperimentConfig, CollectorConfig, ProcmonCollectorConfig

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
            
    def __init__(self, config: ExperimentConfig) -> None:
        super(CollectorController, self).__init__()
        self.config = config
        self.collector: BaseCollector = CollectorController.map_collector(config.collector)
        self.settings = config.settings
        self.is_terminated = Event()
        self.manager = Manager()
        self.shared_state = self.manager.dict()
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
            rc = self.collector.start_collection(self.settings, self.config.runtime)
            if not rc:
                self.shared_state["error_flag"] = True
                self.shared_state["error_string"] = f"Collector finished with return code: {rc}"
        except Exception as ex:
                self.shared_state["error_flag"] = True
                self.shared_state["error_string"] = str(ex)

    def run(self):
        process = Process(target=self.__fork_run, args=())
        
        time.sleep(self.config.delay)

        process.start()
        process.join(self.collector.get_runtime_upper_bound(self.config.runtime) + 1)

        if process.is_alive():
            # TODO: Error, process is still alive -> report
            print("Still runs :(")
            try:
                parent = psutil.Process(process.ident)
                for child in parent.children(recursive=True):
                    try: child.send_signal(signal.SIGTERM)
                    except Exception as ex:
                        # TODO: Log error
                        continue
            except Exception as ex:
                # TODO: Log error
                pass

            process.terminate()
            
        process.join()
        
        print("Has terminated!")
        print(self.shared_state["error_string"])
        self.is_terminated.set()

    def has_terminated(self) -> bool:
        return self.is_terminated.is_set()
    
    def get_experiment_name(self) -> str:
        return self.config.name

config: CollectorConfig = ProcmonCollectorConfig(interfaces=["wlp0s20f3"])

exp: ExperimentConfig = ExperimentConfig("lol", "procmon", runtime=10, settings=config.__dict__)

cont: CollectorController =  CollectorController(exp)
cont.start()
cont.join()
