import subprocess

from typing import Tuple, Optional

from applications.base_application import BaseApplication
from common.application_configs import ApplicationSettings


class PingApplicationConfig(ApplicationSettings):
    def __init__(self, target: str, source: str = None, interval: int = 1,
                 packetsize: int = None, ttl: int = None, timeout: int = 1) -> None:
        self.target = target
        self.source = source
        self.interval = interval
        self.packetsize = packetsize
        self.ttl = ttl
        self.timeout = timeout


class PingApplication(BaseApplication):
    NAME = "ping"

    def set_and_validate_config(self, config: ApplicationSettings) -> Tuple[bool, Optional[str]]:
        try:
            self.settings = PingApplicationConfig(**config)
            return True, None
        except Exception as ex:
            return False, f"Config validation failed: {ex}"

    def start(self, runtime: int) -> bool:
        if self.settings is None:
            return False
        
        command = ["/usr/bin/ping", "-O", "-B", "-D"]

        command.append("-w")
        command.append(str(runtime))

        command.append("-W")
        command.append(str(self.settings.timeout))

        command.append("-i")
        command.append(str(self.settings.interval))

        if self.settings.source is not None:
            command.append("-I")
            command.append(self.settings.source)

        if self.settings.ttl is not None:
            command.append("-t")
            command.append(str(self.settings.ttl))

        if self.settings.packetsize is not None:
            command.append("-s")
            command.append(str(self.settings.packetsize))
    
        command.append(self.settings.target)

        try:
            process = subprocess.Popen(command, shell=False, 
                                       stdout=subprocess.PIPE, 
                                       stderr=subprocess.STDOUT)
        except Exception as ex:
            raise Exception(f"Unable to start ping: {ex}")

        current_seq = 0
        try:
            while process.poll() is None:
                line = process.stdout.readline().decode("utf-8")

                if line is None or line == "":
                    break

                if not line.startswith("["): 
                    continue

                parts = line.split(" ")
                #timestamp = float(parts.pop(0).replace("[", "").replace("]", ""))
                parts.pop(0)

                reachable = True

                if parts[0] == "no" or parts[0] == "From":
                    reachable = False

                results = dict(map(lambda z: (z[0], z[1]), map(lambda y: y.split("="), filter(lambda x: "=" in x, parts))))

                if "icmp_seq" not in results:
                    continue

                icmp_seq = int(results["icmp_seq"])

                if current_seq >= icmp_seq:
                    continue
                current_seq = icmp_seq

                data = {
                    "rtt": float(results.get("time", -1)),
                    "ttl": int(results.get("ttl", -1)),
                    "reachable": reachable,
                    "icmp_seq": icmp_seq
                }
                
                self.interface.data_point("ping", data)

        except Exception as ex:
            raise Exception(f"Ping error: {ex}")

        return process.wait() == 0
