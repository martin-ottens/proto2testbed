#!/usr/bin/python3

from controller import Controller

import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    args = parser.parse_args()

    Controller(args.config).main()
