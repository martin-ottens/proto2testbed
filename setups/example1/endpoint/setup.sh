#!/bin/bash

ip address add $IP_ADDRESS dev enp0s3
ip link set up dev enp0s3
ip r add $ROUTE

if [[ "$WIREGUARD" != "disable" ]]; then
    ip link add dev wg0 type wireguard
    ip address add dev wg0 $WIREGUARD/24
    curl $FILESERVER_ADDRESS/endpoint/wireguard_${INSTANCE_NAME}.conf > /etc/wireguard/wg.conf
    wg setconf wg0 /etc/wireguard/wg.conf
    ip link set up dev wg0
fi
