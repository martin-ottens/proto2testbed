import subprocess

from applications.base_application import BaseApplication
from common.application_configs import ApplicationConfig, PingApplicationConfig
from application_interface import ApplicationInterface


class PingApplication(BaseApplication):
    def start_collection(self, settings: ApplicationConfig, runtime: int, interface: ApplicationInterface) -> bool:
        if not isinstance(settings, PingApplicationConfig):
            raise Exception("Received invalid config type!")
        
        command = ["/usr/bin/ping", "-O", "-B", "-D"]

        command.append("-w")
        command.append(str(runtime))

        command.append("-W")
        command.append(str(settings.timeout))

        command.append("-i")
        command.append(str(settings.interval))

        if settings.source is not None:
            command.append("-I")
            command.append(settings.source)

        if settings.ttl is not None:
            command.append("-t")
            command.append(str(settings.ttl))

        if settings.packetsize is not None:
            command.append("-s")
            command.append(str(settings.packetsize))
    
        command.append(settings.target)

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
                
                interface.data_point("ping", data)

        except Exception as ex:
            raise Exception(f"Ping error: {ex}")

        return process.wait() == 0