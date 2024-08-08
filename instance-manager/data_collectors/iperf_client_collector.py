import subprocess
import json

from data_collectors.base_collector import BaseCollector
from common.collector_configs import CollectorConfig, IperfClientCollectorConfig

class IperfClientCollector(BaseCollector):
    __CONNECT_TIMEOUT = 5

    def get_runtime_upper_bound(self, runtime: int) -> int:
        return runtime + IperfClientCollector.__CONNECT_TIMEOUT

    def start_collection(self, settings: CollectorConfig, runtime: int) -> bool:
        if not isinstance(settings, IperfClientCollectorConfig):
            raise Exception("Received invalid config type!")
        
        command = ["/usr/bin/iperf3", "--json-stream", "--interval", "1", "--forceflush"]

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
                raise Exception("TCP NO DELAY is used together with UDP option")
            command.append("--no-delay")
        
        command.append("--time")
        command.append(str(runtime))

        command.append("--connect-timeout")
        command.append(str(IperfClientCollector.__CONNECT_TIMEOUT))

        command.append("--port")
        command.append(str(settings.port))
        command.append("--client")
        command.append(settings.host)

        try:
            process = subprocess.Popen(command, shell=False, 
                                       stdout=subprocess.PIPE, 
                                       stderr=subprocess.STDOUT)
        except Exception as ex:
            raise Exception(f"Unable to start Iperf3 client: {ex}")

        total_bytes = 0
        total_seconds = 0
        report_index = 0
        try:
            while process.poll() is None:
                line = process.stdout.readline().decode("utf-8")
                if line is None or line == "":
                    break
                json_line = json.loads(line)

                match json_line["event"]:
                    case "error":
                        raise Exception(json_line["data"])
                    case "interval":
                        report_index  += 1
                        total_bytes   += json_line["data"]["sum"]["bytes"]
                        total_seconds += json_line["data"]["sum"]["seconds"]
                        this_bps       = json_line["data"]["sum"]["bits_per_second"]
                        print(f"{report_index}: bytes={total_bytes},seonds={total_seconds},bps={this_bps}")
                    case _:
                        continue

        except Exception as ex:
            raise Exception(f"Iperf3 error: {ex}")

        return process.returncode == 0
