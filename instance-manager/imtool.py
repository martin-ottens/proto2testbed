#!/usr/bin/python3

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

    parser_log = subparsers.add_parser("log", help="Send a log message to the Testbed Controller")
    parser_log.add_argument("--level", "-l", type=str, choices=["SUCCESS", "INFO", "WARNING", "ERROR", "DEBUG"], 
                            required=False, default="INFO", help="Log-Level")
    parser_log.add_argument("message", type=str, nargs=argparse.REMAINDER, help="Log message")

    parser_data = subparsers.add_parser("data", help="Save a data point to the Time Series Database")
    parser_data.add_argument("--measurement", "-m", type=str, required=True, help="Name of the measurement")
    parser_data.add_argument("--tag", "-t", action="append", help="Additonal tags, instance name and experiment tag will be added automatically")
    parser_data.add_argument("points", nargs="+", help="Data points in the format NAME:VALUE")

    args = parser.parse_args()

    payload = {"type": args.command}
    match args.command:
        case "preserve":
            try:
                if not Path(args.path).exists():
                    raise Exception("Path does not exist")
            except Exception as ex:
                print(f"Invalid Path '{args.path}': {ex}", file=sys.stderr)
                sys.exit(1)
            payload["path"] = args.path
        case "status":
            pass
        case "log":
            payload["level"] = args.level
            payload["message"] = ' '.join(args.message)
        case "data":
            if args.tag:
                payload["tags"] = args.tag
            
            points = {}
            for point in args.points:
                if not re.match(r"^[A-Za-z]+:(-?\d+(\.\d+)?|-?\.\d+)$", point):
                    print(f"Invalid  data point: {point}", file=sys.stderr)
                    sys.exit(1)
                name, value = point.split(":")
                points[name] = value
        case _:
            print(f"Invalid subcommand '{args.command}'", file=sys.stderr)
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
        status = result["status"]

        if "message" in result:
            print(f"Instance Manager Error: {result['message']}", file=sys.stderr)
        
        if args.command == "status":
            if status:
                print("Instance Manager Daemon is ready.")
            else:
                print("Instance Manager Daemon is not ready.")

        sys.exit(status)
    except Exception as ex:
        print(f"Unable to communicate with Instance Manager Daemon: {ex}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
