#!/usr/bin/python3
#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2024-2025 Martin Ottens
# 
# This program is free software: you can redistribute it and/or modify 
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful, 
# but WITHOUT ANY WARRANTY; without even the implied warranty of 
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the 
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License 
# along with this program. If not, see https://www.gnu.org/licenses/.
#

import argparse
import re
import sys
import socket
import json

from pathlib import Path

IM_SOCKET_PATH = "/tmp/im.sock"


def main():
    parser = argparse.ArgumentParser(prog="im", description="Instance Manager CLI Tool")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Action to perform")

    parser_preserve = subparsers.add_parser("preserve", help="Select a file or directory to preserve after shutdown")
    parser_preserve.add_argument("path", type=str, help="Path to file or directory")

    parser_status = subparsers.add_parser("status", help="Shows the status of the Instance Manager Daemon")

    parser_shutdown = subparsers.add_parser("shutdown", help="Shuts down the whole testbed")
    parser_shutdown.add_argument("--restart", "-r", default=False, action="store_true",
                                 help="Request a restart after testbed shutdown")

    parser_log = subparsers.add_parser("log", help="Send a log message to the Testbed Controller")
    parser_log.add_argument("--level", "-l", type=str, choices=["SUCCESS", "INFO", "WARNING", "ERROR", "DEBUG"], 
                            required=False, default="INFO", help="Log-Level")
    parser_log.add_argument("message", type=str, nargs=argparse.REMAINDER, help="Log message")

    parser_data = subparsers.add_parser("data", help="Save a data point to the Time Series Database")
    parser_data.add_argument("--measurement", "-m", type=str, required=True, help="Name of the measurement")
    parser_data.add_argument("--tag", "-t", action="append", help="Additional tags in format NAME:VALUE, instance name and experiment tag will be added automatically")
    parser_data.add_argument("points", nargs="+", help="Data points in format NAME:VALUE")

    args = parser.parse_args()

    payload = {"type": args.command}
    match args.command:
        case "shutdown":
            payload["restart"] = args.restart
        case "status":
            pass
        case "preserve":
            if not Path(args.path).exists():
                print(f"Error: Invalid Path '{args.path}': No such file or directory.", file=sys.stderr)
                sys.exit(1)
                
            payload["path"] = str(Path(args.path).resolve())
        case "log":
            payload["level"] = args.level
            payload["message"] = ' '.join(args.message)
        case "data":
            payload["measurement"] = args.measurement

            tags = {}
            if args.tag:
                for tag in args.tag:
                    if not re.match(r"^[a-zA-Z]+:[\S]+$", tag):
                        print(f"Invalid tag: '{tag}' (Required format: <TAG>:<VALUE>)", file=sys.stderr)
                        sys.exit(1)
                    name, value = tag.split(":")
                    tags[name] = value
            payload["tags"] = tags
            
            points = {}
            for point in args.points:
                if not re.match(r"^[A-Za-z0-9]+:(-?\d+(\.\d+)?|-?\.\d+)$", point):
                    print(f"Invalid data point: '{point}' (Required format: <NAME>:<VALUE>, VALUE = int or float)", file=sys.stderr)
                    sys.exit(1)
                name, value = point.split(":")
                fval = float(value)
                if fval.is_integer():
                    points[name] = int(fval)
                else:
                    points[name] = fval
            payload["points"] = points
        case _:
            print(f"Invalid subcommand '{args.command}', add -h for an help.", file=sys.stderr)
            sys.exit(1)

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(1)
        sock.connect(IM_SOCKET_PATH)
    except Exception as ex:
        print(f"Unable to connect to Instance Manager Daemon: {ex}", file=sys.stderr)
        sys.exit(1)

    try:
        sock.sendall(json.dumps(payload).encode("utf-8") + b'\n')
        json_result = sock.recv(4096)
        result = json.loads(json_result)
        sock.close()
        status = result["status"]

        if "message" in result:
            print(f"Instance Manager Error: {result['message']}", file=sys.stderr)
        
        if args.command == "status":
            if status == "ok":
                print("Instance Manager Daemon is ready.")
            else:
                print("Instance Manager Daemon is not ready.")

        sys.exit(status != "ok")
    except Exception as ex:
        print(f"Unable to communicate with Instance Manager Daemon: {ex}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
