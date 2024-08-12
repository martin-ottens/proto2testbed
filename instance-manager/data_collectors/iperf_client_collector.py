import traceback

from data_collectors.base_collector import BaseCollector
from data_collectors.iperf_common import run_iperf
from data_collectors.influxdb_adapter import InfluxDBAdapter
from common.collector_configs import CollectorConfig, IperfClientCollectorConfig

class IperfClientCollector(BaseCollector):
    __CONNECT_TIMEOUT_MULTIPLIER = 0.1
    __STATIC_DELAY_BEFORE_START = 5

    def get_runtime_upper_bound(self, runtime: int) -> int:
        return runtime + int(IperfClientCollector.__CONNECT_TIMEOUT_MULTIPLIER * runtime) + IperfClientCollector.__STATIC_DELAY_BEFORE_START

    def start_collection(self, settings: CollectorConfig, runtime: int, adapter: InfluxDBAdapter) -> bool:
        if not isinstance(settings, IperfClientCollectorConfig):
            raise Exception("Received invalid config type!")
        
        command = ["/usr/bin/iperf3", "--forceflush"]

        if settings.reverse is True:
            command.append("--reverse")

        if settings.udp is True:
            if settings.bandwidth_kbps is None:
                raise Exception("Iperf3 Client UDP Settings needs bandwidth!")
            command.append("--udp")
        
        if settings.bandwidth_kbps is not None:
            command.append("--bandwidth")
            command.append(f"{settings.bandwidth_kbps}k")
        
        if settings.streams is not None:
            command.append("--parallel")
            command.append(str(settings.streams))
        
        if settings.tcp_no_delay is True:
            if settings.udp is True:
                raise Exception("TCP_NO_DELAY is used together with UDP option")
            command.append("--no-delay")
        
        command.append("--time")
        command.append(str(runtime))

        command.append("--interval")
        command.append(str(settings.report_interval))

        command.append("--connect-timeout")
        command.append(str(max(IperfClientCollector.__STATIC_DELAY_BEFORE_START, IperfClientCollector.__CONNECT_TIMEOUT_MULTIPLIER * runtime)))

        command.append("--port")
        command.append(str(settings.port))
        command.append("--client")
        command.append(settings.host)

        try:
           return run_iperf(command, adapter) == 0
        except Exception as ex:
            traceback.print_exception(ex)
            raise Exception(f"Iperf3 server error: {ex}")


