#!/bin/bash

ip address add $IP_ADDRESS dev enp0s3
ip link set up dev enp0s3

ip r add $ROUTE dev enp0s3
