import time
import subprocess

from typing import List, Tuple, Optional

from applications.base_application import *
from common.application_configs import ApplicationSettings

"""
Parse 'tc -s qdisc sh' for a given list of interfaces. Supported qdiscs: netem, tbf
Two list are provided: "netem_if" for the interfaces that should be monitored for
netem stats and "tbf_if" that should be monitored for tbf statistics. Stats will
be queried every "interval" seconds (defaults to one).

At least one interface needs to be defined in "netem_if" or "tbf_if". Use null
to disable monitoring of a specific qdisc type.

Example config:
    {
        "application": "apps/qdisc_stats.py",
        "name": "qdisc_router",
        "delay": 0,
        "runtime": 60,
        "settings": {
            "interval": 1, // every second
            "netem_if": ["enp0s3", "enp0s4"], // monitor 'netem' qdisc on enp0s{3,4}
            "tbf_if": ["enp0s3", "enp0s4"] // monitor 'tbf' qdisc on enp0s{3,4}
        }
    }
"""

class QdiscStatsApplicationConfig(ApplicationSettings):
    def __init__(self, interval: int = 1, 
                 netem_if: Optional[List[str]] = None, 
                 tbf_if: Optional[List[str]] = None)  -> None:
        self.interval = interval
        self.netem_if = netem_if
        self.tbf_if = tbf_if

class QdiscStatsApplication(BaseApplication):
    NAME = "qdisc-stats"

    def set_and_validate_config(self, config: ApplicationSettings) -> Tuple[bool, Optional[str]]:
        try:
            self.settings = QdiscStatsApplicationConfig(**config)
            count = 0
            if self.settings.netem_if is not None:
                count += len(self.settings.netem_if)
            if self.settings.tbf_if is not None:
                count += len(self.settings.tbf_if)

            if count == 0:
                return False, "No interfaces for tc qdisc monitoring configured."
            else:
                return True, None
        except Exception as ex:
            return False, f"Config validation failed: {ex}"
        
    def __interpret_number(self, input: str):
        units = {
            "k": 1_000,
            "K": 1_000,
            "M": 1_000_000,
            "G": 1_000_000_000,
            "T": 1_000_000_000_000,
            "b": 1,
            "B": 8,
            "p": 1
        }

        if input[-1].isalpha():
            number_part = float(input[:-1])

            if input[-1] in units:
                return int(number_part * units[input[-1]])
            else:
                raise Exception(f"Unsupported Unit: {input[-1]}")
        else:
            return int(input)
        
    def __parse_single_stat(self, input: str):
        result = {}

        # Sent %i bytes %s pkt
        _, sent_bytes, _, sent_packets, _, remain = input.split(" ", maxsplit=5)
        result["sent_bytes"] = self.__interpret_number(sent_bytes)
        result["sent_packets"] = self.__interpret_number(sent_packets)

        # (dropped %i, overlimits %i requeues %i)
        _, dropped_dirty, _, overlimits, _, requeues_dirty, remain = remain.split(" ", maxsplit=6)
        result["dropped"] = self.__interpret_number(dropped_dirty.replace(",", ""))
        result["overlimits"] = self.__interpret_number(overlimits)
        result["sent_requeues"] = self.__interpret_number(requeues_dirty.replace(")", ""))

        # backlog %ib %ip requeues %i <remainder>
        parts = remain.split(" ", maxsplit=5)
        if len(parts) == 5:
            _, backlog_b_dirty, backlog_p_dirty, _, requeues = parts
        else:
            _, backlog_b_dirty, backlog_p_dirty, _, requeues, _ = parts
        result["backlog_bytes"] = self.__interpret_number(backlog_b_dirty[:-1])
        result["backlog_packets"] = self.__interpret_number(backlog_p_dirty[:-1])
        result["backlog_requeues"] = self.__interpret_number(requeues)

        return result
    
    def __get_one_datapoint(self, input: str):
        results = []
        context = None
        for line in input.split("\n"):
            if line.startswith("qdisc"):
                if context is not None:
                    results.append(context)
                    context = None

                _, qdisc, remain = line.split(" ", maxsplit=2)
                if qdisc not in ["netem", "tbf"]:
                    continue
                else:
                    handle, remain = remain.split(":", maxsplit=1)
                    remain = remain.strip()
                    _, dev, _ = remain.split(" ", maxsplit=2)
                    context = {
                        "qdisc": qdisc,
                        "handle": int(handle),
                        "dev": dev,
                        "stats": []
                    }
            else:
                if line.startswith("  "):
                    continue
                if context is not None:
                    context["stats"].append(line.strip())

        for result in results:
            if result["qdisc"] == "netem":
                if self.settings.netem_if is None:
                    continue
                if result["dev"] not in self.settings.netem_if:
                    continue
            elif result["qdisc"] == "tbf":
                if self.settings.tbf_if is None:
                    continue
                if result["dev"] not in self.settings.tbf_if:
                    continue
            else:
                continue

            stats_string = " ".join(result["stats"])
            stats = self.__parse_single_stat(stats_string)
            
            self.interface.data_point("qdisc-stats", stats, {
                "dev": result["dev"],
                "qdisc": result["qdisc"],
                "handle": str(result["handle"])
            })
        
        for dev in self.settings.netem_if:
            if not len(list(filter(lambda x: x["qdisc"] == "netem" and x["dev"] == dev, results))):
                raise Exception(f"Interface '{dev}' not found for qdisc netem.")
        
        for dev in self.settings.tbf_if:
            if not len(list(filter(lambda x: x["qdisc"] == "tbf" and x["dev"] == dev, results))):
                raise Exception(f"Interface '{dev}' not found for qdisc tbf.")

    def start(self, runtime: int) -> bool:
        end_at = time.time() + runtime
        while end_at > time.time():
            proc = subprocess.run(["/usr/sbin/tc", "-s", "qdisc", "sh"], capture_output=True, shell=False)
            if proc.returncode != 0:
                raise Exception(f"Unable to run 'tc' command: {proc.stderr.decode('utf-8')}")
            
            self.__get_one_datapoint(proc.stdout.decode('utf-8'))
            time.sleep(self.settings.interval)
        
        return True

    def get_export_mapping(self, subtype: ExportSubtype) -> Optional[List[ExportResultMapping]]:        
        return [
            ExportResultMapping(
                name="sent_bytes",
                type=ExportResultDataType.DATA_SIZE,
                description="Bytes sent via Qdisc",
                additional_selectors={"dev": subtype.options["dev"], "qdisc": subtype.options["qdisc"]},
                title_suffix=f'Interface: {subtype.options["dev"]}, Qdisc: {subtype.options["qdisc"]}'
            ),
            ExportResultMapping(
                name="sent_packets",
                type=ExportResultDataType.COUNT,
                description="Packets sent via Qdisc",
                additional_selectors={"dev": subtype.options["dev"], "qdisc": subtype.options["qdisc"]},
                title_suffix=f'Interface: {subtype.options["dev"]}, Qdisc: {subtype.options["qdisc"]}'
            ),
            ExportResultMapping(
                name="dropped",
                type=ExportResultDataType.COUNT,
                description="Dropped Packets",
                additional_selectors={"dev": subtype.options["dev"], "qdisc": subtype.options["qdisc"]},
                title_suffix=f'Interface: {subtype.options["dev"]}, Qdisc: {subtype.options["qdisc"]}'
            ),
            ExportResultMapping(
                name="overlimits",
                type=ExportResultDataType.COUNT,
                description="Packets delayed due to overlimit",
                additional_selectors={"dev": subtype.options["dev"], "qdisc": subtype.options["qdisc"]},
                title_suffix=f'Interface: {subtype.options["dev"]}, Qdisc: {subtype.options["qdisc"]}'
            ),
            ExportResultMapping(
                name="sent_requeues",
                type=ExportResultDataType.DATA_SIZE,
                description="Packets requeued before sending",
                additional_selectors={"dev": subtype.options["dev"], "qdisc": subtype.options["qdisc"]},
                title_suffix=f'Interface: {subtype.options["dev"]}, Qdisc: {subtype.options["qdisc"]}'
            ),
            ExportResultMapping(
                name="backlog_bytes",
                type=ExportResultDataType.DATA_SIZE,
                description="Bytes held by Qdisc and childs",
                additional_selectors={"dev": subtype.options["dev"], "qdisc": subtype.options["qdisc"]},
                title_suffix=f'Interface: {subtype.options["dev"]}, Qdisc: {subtype.options["qdisc"]}'
            ),
            ExportResultMapping(
                name="backlog_packets",
                type=ExportResultDataType.COUNT,
                description="Packets held by Qdisc and childs",
                additional_selectors={"dev": subtype.options["dev"], "qdisc": subtype.options["qdisc"]},
                title_suffix=f'Interface: {subtype.options["dev"]}, Qdisc: {subtype.options["qdisc"]}'
            ),
            ExportResultMapping(
                name="backlog_requeues",
                type=ExportResultDataType.COUNT,
                description="Packets requeued to backlog",
                additional_selectors={"dev": subtype.options["dev"], "qdisc": subtype.options["qdisc"]},
                title_suffix=f'Interface: {subtype.options["dev"]}, Qdisc: {subtype.options["qdisc"]}'
            ),
        ]
