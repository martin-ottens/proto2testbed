#!/bin/bash

ip address add $IP_ADDRESS_0 dev eth1
ip link set up dev eth1

ip address add $IP_ADDRESS_1 dev eth2
ip link set up dev eth2

sysctl -w net.ipv4.ip_forward=1
