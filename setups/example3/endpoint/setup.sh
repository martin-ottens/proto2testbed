#!/bin/bash

ip address add $IP_ADDRESS dev eth1
ip link set up dev eth1

ip r add $ROUTE dev eth1
