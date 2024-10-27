import argparse
import re

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

    if args.command == "preserve":
        print(f"Preserve file: {args.path}")

    elif args.command == "status":
        print("Show status")

    elif args.command == "log":
        print(f"Log-Level: {args.level}")
        print(f"Message: {' '.join(args.message)}")

    elif args.command == "data":
        print(f"Infux Data: {args.measurement}")
        for point in args.points:
            if not re.match(r"^[A-Za-z]+:(-?\d+(\.\d+)?|-?\.\d+)$", point):
                print(f"Invalid point: {point}")
                continue
            name, value = point.split(":")
            print(f"Data Point: {name}, {value}")

        if args.tag:
            for tag in args.tag:
                print(f"Additional tag: {tag}")

if __name__ == "__main__":
    main()
