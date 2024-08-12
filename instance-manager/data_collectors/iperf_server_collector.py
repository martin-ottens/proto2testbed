import traceback

from data_collectors.base_collector import BaseCollector
from data_collectors.iperf_common import run_iperf
from data_collectors.influxdb_adapter import InfluxDBAdapter
from common.collector_configs import CollectorConfig, IperfServerCollectorConfig

class IperfServerCollector(BaseCollector):
    def get_runtime_upper_bound(self, runtime: int) -> int:
        return runtime * 2

    def start_collection(self, settings: CollectorConfig, runtime: int, adapter: InfluxDBAdapter) -> bool:
        if not isinstance(settings, IperfServerCollectorConfig):
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
