#!/bin/bash

ip address add 10.0.0.2/24 dev enp0s3
ip link set up dev enp0s3
