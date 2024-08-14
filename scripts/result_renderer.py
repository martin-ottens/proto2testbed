#!/usr/bin/python3

import argparse
import json
import os
import sys

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

import dateutil.parser as dateparser

from influxdb import InfluxDBClient
from loguru import logger
from typing import List, Optional, Tuple

OUTPUT_TYPE = "pdf"

MILLISECONDS = "ms"
SECONDS = "s"
DATA_SIZE = "bytes"
DATA_RATE = "bits/s"

# TODO: procmon change _ to -
MAPPING = {
    "ping": {
        "time": (MILLISECONDS, "ICMP RTT"),
        "ttl": (None, "TTL of response packet"),
        "reachable": (None, "Target reachable")
    },
    "iperf-tcp-client": {
        "transfer": (DATA_SIZE, "Transfer Size"),
        "bitrate": (DATA_RATE, "Transfer Bitrate"),
        "retransmit": (None, "Number of Retransmits"),
        "congestion": (DATA_SIZE, "Congestion Window Size")
    },
    "iperf-tcp-server": {
        "transfer": (DATA_SIZE, "Transfer Size"),
        "bitrate": (DATA_RATE, "Transfer Bitrate")
    },
    "iperf-udp-client": {
        "transfer": (DATA_SIZE, "Transfer Size"),
        "bitrate": (DATA_RATE, "Transfer Bitrate"),
        "datagrams": (None, "Number of UDP datagrams"),
    },
    "iperf-udp-server": {
        "transfer": (DATA_SIZE, "Transfer Size"),
        "bitrate": (DATA_RATE, "Transfer Bitrate"),
        "jitter": (MILLISECONDS, "Transfer Jitter"),
        "datagrams_lost": (None, "Number of lost UDP datagrams"),
        "datagrams_total": (None, "Number of total UDP datagrams")
    },
    "proc-system": {
        "cpu_user": (SECONDS, "User CPU Time"),
        "cpu_system": (SECONDS, "System/Kernel CPU Time"),
        "cpu_idle": (SECONDS, "Idle CPU Time"),
        "mem_used": (DATA_SIZE, "Used System Memory"),
        "mem_free": (DATA_SIZE, "Free System Memory")
    },
    "proc-process": {
        "cpu_user": (SECONDS, "Process CPU User Time"),
        "cpu_system": (SECONDS, "Process CPU System Time"),
        "mem_rss": (DATA_SIZE, "Process Memory Resident Set Size"),
        "mem_vms": (DATA_SIZE, "Process Virtual Memory Size"),
        "mem_shared": (DATA_SIZE, "Proces Shared Memory Size")
    },
    "proc-interface": {
        "bytes_sent": (DATA_SIZE, "Bytes sent via Interface"),
        "bytes_recv": (DATA_SIZE, "Bytes received via Interface"),
        "packets_sent": (None, "Packets sent via Interface"),
        "packets_recv": (None, "Packets received via Interface"),
        "errin": (None, "Interface Input Errors"),
        "errout": (None, "Interface Output Errors"),
        "dropin": (None, "Interface Input Drops"),
        "dropout": (None, "Interface Output Drops")
    }
}

def bytes_to_human_readable(x, pos):
    if x >= 1e9:
        return f'{x / 1e9:.1f} GB'
    elif x >= 1e6:
        return f'{x / 1e6:.1f} MB'
    elif x >= 1e3:
        return f'{x / 1e3:.1f} KB'
    else:
        return f'{x:.1f} B'

def bits_to_human_readable(x, pos):
    if x >= 1e9:
        return f'{x / 1e9:.1f} Gbps'
    elif x >= 1e6:
        return f'{x / 1e6:.1f} Mbps'
    elif x >= 1e3:
        return f'{x / 1e3:.1f} Kbps'
    else:
        return f'{x:.1f} bps'

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
    
    def plot_one(filename: str, field: str, generator, plotinfo: Tuple[Optional[str], str], collector_delay: int, title: str):
        results = []
        for entry in generator:
            results.append((int(dateparser.parse(entry["time"]).timestamp()), entry[field]))

        t_0 = min(map(lambda x: x[0], results))
        x = []
        y = []
        for entry in results:
            x.append(entry[0] - t_0 + collector_delay)
            y.append(entry[1])
        
        fig, ax = plt.subplots()
        ax.plot(np.array(x), np.array(y))
        plt.xlabel("Seconds")
        plt.ylabel(f"{plotinfo[1]} {f'({plotinfo[0]})' if plotinfo[0] is not None else ''}")

        if plotinfo[0] == DATA_SIZE:
            ax.yaxis.set_major_formatter(ticker.FuncFormatter(bytes_to_human_readable))
        elif plotinfo[0] == DATA_RATE:
            ax.yaxis.set_major_formatter(ticker.FuncFormatter(bits_to_human_readable))
        plt.title(title, fontsize=5)
        plt.tight_layout()
        plt.savefig(filename)
        plt.close()
        logger.success(f"Plot rendered to file: {filename}")

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
                path = f"{basepath}/{item[0]}_{field}.{OUTPUT_TYPE}"
                plot_one(path, field, data, plotinfo, collector_delay, 
                         f"Experiment: {experiment}, Series: {collector_name}@{machine_name}, Collector: {field}@{item[0]}{add_title}")


    with open(config, "r") as handle:
        testbed = json.load(handle)

    os.makedirs(out, exist_ok=True)

    for machine in testbed["machines"]:
        machine_name = machine["name"]
        logger.info(f"Processing instance {machine_name}")
        os.makedirs(f"{out}/{machine_name}", exist_ok=True)
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
    parser.add_argument("--renderout", type=str, help="Image output path", required=False, default="./out")
    args = parser.parse_args()

    try:
        if args.influx_user is not None:
            client = InfluxDBClient(host=args.influx_host, port=args.influx_port, 
                                    user=args.influx_user, password=args.influx_pass)
        else:
            client = InfluxDBClient(host=args.influx_host, port=args.influx_port)

        client.switch_database(args.influx_database)

        main(client, args.experiment, args.config, args.renderout)
    except Exception as ex:
        logger.opt(exception=ex).critical("Exception during execution")
        sys.exit(1)
    finally:
        client.close()
    
