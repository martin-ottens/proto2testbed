#!/bin/bash

ip address add $IP_ADDRESS_0 dev enp0s3
ip link set up dev enp0s3

ip address add $IP_ADDRESS_1 dev enp0s4
ip link set up dev enp0s4

sysctl -w net.ipv4.ip_forward=1

curl $FILESERVER_ADDRESS/router/application.sh > /tmp/application.sh
chmod +x /tmp/application.sh
