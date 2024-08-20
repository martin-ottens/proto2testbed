import traceback

from applications.base_application import BaseApplication
from applications.iperf_common import run_iperf
from applications.influxdb_adapter import InfluxDBAdapter
from common.application_configs import ApplicationConfig, IperfServerApplicationConfig

class IperfServerApplication(BaseApplication):
    def get_runtime_upper_bound(self, runtime: int) -> int:
        return runtime * 2

    def start_collection(self, settings: ApplicationConfig, runtime: int, adapter: InfluxDBAdapter) -> bool:
        if not isinstance(settings, IperfServerApplicationConfig):
            raise Exception("Received invalid config type!")
        
        command = ["/usr/bin/iperf3", "--forceflush", "--one-off"]

        command.append("--interval")
        command.append(str(settings.report_interval))

        command.append("--port")
        command.append(str(settings.port))
        command.append("--server")
        command.append(settings.host)

        try:
           return run_iperf(command, adapter) == 0
        except Exception as ex:
            traceback.print_exception(ex)
            raise Exception(f"Iperf3 server error: {ex}")
