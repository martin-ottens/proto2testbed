#!/usr/bin/python3

import argparse
import sys
from influxdb import InfluxDBClient
from loguru import logger


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", type=str, help="Experiment tag name", required=True)
    parser.add_argument("--influx_database", type=str, help="InfluxDB database", required=True)
    parser.add_argument("--influx_host", type=str, help="InfluxDB host", required=False, default="127.0.0.1")
    parser.add_argument("--influx_port", type=int, help="InfluxDB port", required=False, default=8086)
    parser.add_argument("--influx_user", type=str, help="InfluxDB user", required=False, default=None)
    parser.add_argument("--influx_pass", type=str, help="InfluxDB password", required=False, default=None)
    args = parser.parse_args()

    try:
        if args.influx_user is not None:
            client = InfluxDBClient(host=args.influx_host, port=args.influx_port, 
                                    user=args.influx_user, password=args.influx_pass)
        else:
            client = InfluxDBClient(host=args.influx_host, port=args.influx_port)

        client.switch_database(args.influx_database)

        client.delete_series(tags={"experiment": args.experiment})
        logger.success(f"All data with tag={args.experiment} deleted")
    except Exception as ex:
        logger.opt(exception=ex).critical("Exception during deletion")
        sys.exit(0)
    finally:
        client.close()
