#!/bin/bash

ip address add 10.0.0.2/24 dev eth1
ip link set up dev eth1
