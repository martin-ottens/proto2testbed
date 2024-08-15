#!/usr/bin/python3

import argparse
import json
import os
import sys

import dateutil.parser as dateparser

from influxdb import InfluxDBClient
from loguru import logger
from typing import List, Optional, Tuple

MILLISECONDS = "ms"
SECONDS = "s"
DATA_SIZE = "bytes"
DATA_RATE = "bps"
COUNT = "count"

MAPPING = {
    "ping": {
        "rtt": MILLISECONDS,
        "ttl": "ttl",
        "reachable": "boolean"
    },
    "iperf-tcp-client": {
        "transfer": DATA_SIZE,
        "bitrate": DATA_RATE,
        "retransmit": COUNT,
        "congestion": DATA_SIZE
    },
    "iperf-tcp-server": {
        "transfer": DATA_SIZE,
        "bitrate": DATA_RATE
    },
    "iperf-udp-client": {
        "transfer": DATA_SIZE,
        "bitrate": DATA_RATE,
        "datagrams": COUNT,
    },
    "iperf-udp-server": {
        "transfer": DATA_SIZE,
        "bitrate": DATA_RATE,
        "jitter": MILLISECONDS,
        "datagrams_lost": COUNT,
        "datagrams_total": COUNT
    },
    "proc-system": {
        "cpu_user": SECONDS,
        "cpu_system": SECONDS,
        "cpu_idle": SECONDS,
        "mem_used": DATA_SIZE,
        "mem_free": DATA_SIZE
    },
    "proc-process": {
        "cpu_user": SECONDS,
        "cpu_system": SECONDS,
        "mem_rss": DATA_SIZE,
        "mem_vms": DATA_SIZE,
        "mem_shared": DATA_SIZE
    },
    "proc-interface": {
        "bytes_sent": DATA_SIZE,
        "bytes_recv": DATA_SIZE,
        "packets_sent": COUNT,
        "packets_recv": COUNT,
        "errin": COUNT,
        "errout": COUNT,
        "dropin": COUNT,
        "dropout": COUNT
    }
}

def main(client: InfluxDBClient, experiment: str, config: str, out: str):

    def map_collector_to_type(machine_name: str, collector_name: str, collector_type: str) -> List[Tuple[str, Optional[str]]]:
    
        list = client.get_list_series(tags={"experiment": experiment, "collector": collector_name, "instance": machine_name})

        if collector_type == "iperf3-server" or collector_type == "iperf3-client":
            if len(list) != 1:
                raise Exception("Invalid number of series for iperf common!")

            item = list[0].split(',')[0]
            if item not in MAPPING.keys():
                raise Exception(f"Invalid iperf common mode {item}")
            
            return [(item, None, )]
        
        if collector_type == "procmon":
            result = []
            for entry in list:
                items = entry.split(",")
                mode = items.pop(0)

                if mode not in MAPPING.keys():
                    raise Exception(f"Invalid iperf common mode {mode}")

                options = {k: v for k, v in map(lambda y: (y[0], y[1], ), map(lambda x: x.split("="), items))}

                if mode == "proc-system":
                    result.append((mode, None, ))
                elif mode == "proc-process":
                    result.append((mode, options["process"], ))
                elif mode == "proc-interface":
                    result.append((mode, options["interface"], ))
        
            return result
        
        return [(collector_type, )]
    
    def export_one(filename: str, field: str, generator, plotinfo: str, collector_delay: int, title: str):
        results = []
        for entry in generator:
            results.append((int(dateparser.parse(entry["time"]).timestamp()), entry[field]))

        t_0 = min(map(lambda x: x[0], results))
        with open(filename, "w") as handle:
            handle.write(f"time,{plotinfo}\n")
            for entry in results:
                handle.write(f"{entry[0] - t_0 + collector_delay},{entry[1]}\n")

        logger.success(f"Series  to file: {filename}")

    def handle_one_series(basepath: str, machine_name: str, collector_name: str, collector_data: List[Tuple[str, Optional[str]]], collector_delay: int):
        def query_normal(field, measurement):
            bind_params = {
                "experiment": experiment,
                "instance": machine_name,
                "collector": collector_name,
            }
            data = client.query(f"SELECT \"{field}\" FROM \"{measurement}\" WHERE \"collector\" = $collector AND \"experiment\" = $experiment AND \"instance\" = $instance", bind_params=bind_params)
            return data.get_points()

        def query_process(field, measurement, process):
            bind_params = {
                "experiment": experiment,
                "instance": machine_name,
                "collector": collector_name,
                "process": process
            }
            data = client.query(f"SELECT \"{field}\" FROM \"{measurement}\" WHERE \"collector\" = $collector AND \"experiment\" = $experiment AND \"instance\" = $instance AND \"process\" = $process", bind_params=bind_params)
            return data.get_points()

        def query_interface(field, measurement, interface):
            bind_params = {
                "experiment": experiment,
                "instance": machine_name,
                "collector": collector_name,
                "interface": interface
            }
            data = client.query(f"SELECT \"{field}\" FROM \"{measurement}\" WHERE \"collector\" = $collector AND \"experiment\" = $experiment AND \"instance\" = $instance AND \"interface\" = $interface", bind_params=bind_params)
            return data.get_points()

        for item in collector_data:
            logger.info(f"------> Processing collector entry {item[0]}")
            for field, plotinfo in MAPPING[item[0]].items():
                match item[0]:
                    case "proc-process":
                        data = query_process(field, item[0], item[1])
                        add_title = f", Process: {item[1]}"
                    case "proc-interface":
                        data = query_interface(field, item[0], item[1])
                        add_title = f", Interface: {item[1]}"
                    case _:
                        data = query_normal(field, item[0])
                        add_title = ""
                logger.info(f"--------> Processing field {field}")
                path = f"{basepath}/{item[0]}_{field}.csv"
                export_one(path, field, data, plotinfo, collector_delay, 
                         f"Experiment: {experiment}, Series: {collector_name}@{machine_name}, Collector: {field}@{item[0]}{add_title}")


    with open(config, "r") as handle:
        testbed = json.load(handle)

    os.makedirs(out, exist_ok=True)

    for machine in testbed["machines"]:
        machine_name = machine["name"]
        logger.info(f"Processing instance {machine_name}")
        os.makedirs(f"{out}/{machine_name}", exist_ok=True)

        if machine["collectors"] is None:
            logger.warning(f"No experiments found for instance {machine_name}")
            continue

        for collector in machine["collectors"]:
            collector_type = collector["collector"]
            collector_name = collector["name"]
            collector_delay = collector.get("delay", 0)
            logger.info(f"--> Processing collector {collector_name}")
            os.makedirs(f"{out}/{machine_name}/{collector_name}", exist_ok=True)
            handle_one_series(f"{out}/{machine_name}/{collector_name}", machine_name, collector_name,
                              map_collector_to_type(machine_name, collector_name, collector_type), collector_delay)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, help="Path to Testbed config", required=True)
    parser.add_argument("--experiment", type=str, help="Experiment tag name", required=True)
    parser.add_argument("--influx_database", type=str, help="InfluxDB database", required=True)
    parser.add_argument("--influx_host", type=str, help="InfluxDB host", required=False, default="127.0.0.1")
    parser.add_argument("--influx_port", type=int, help="InfluxDB port", required=False, default=8086)
    parser.add_argument("--influx_user", type=str, help="InfluxDB user", required=False, default=None)
    parser.add_argument("--influx_pass", type=str, help="InfluxDB password", required=False, default=None)
    parser.add_argument("--output", type=str, help="Export output path", required=False, default="./out")
    args = parser.parse_args()

    try:
        if args.influx_user is not None:
            client = InfluxDBClient(host=args.influx_host, port=args.influx_port, 
                                    user=args.influx_user, password=args.influx_pass)
        else:
            client = InfluxDBClient(host=args.influx_host, port=args.influx_port)

        client.switch_database(args.influx_database)

        main(client, args.experiment, args.config, args.output)
    except Exception as ex:
        logger.opt(exception=ex).critical("Exception during execution")
        sys.exit(1)
    finally:
        client.close()
    
