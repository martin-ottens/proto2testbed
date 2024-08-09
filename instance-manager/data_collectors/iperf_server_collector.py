import json
import subprocess

from data_collectors.base_collector import BaseCollector
from common.collector_configs import CollectorConfig, IperfServerCollectorConfig

class IperfServerCollector(BaseCollector):
    def get_runtime_upper_bound(self, runtime: int) -> int:
        return runtime * 2

    def start_collection(self, settings: CollectorConfig, runtime: int) -> bool:
        if not isinstance(settings, IperfServerCollectorConfig):
            raise Exception("Received invalid config type!")
        
        command = ["/usr/bin/iperf3", "--json-stream", "--forceflush", "--one-off"]

        command.append("--interval")
        command.append(str(settings.report_interval))

        command.append("--port")
        command.append(str(settings.port))
        command.append("--server")
        command.append(settings.host)

        try:
            process = subprocess.Popen(command, shell=False, 
                                       stdout=subprocess.PIPE, 
                                       stderr=subprocess.STDOUT)
        except Exception as ex:
            raise Exception(f"Unable to start Iperf3 server: {ex}")

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

        return process.wait() == 0
