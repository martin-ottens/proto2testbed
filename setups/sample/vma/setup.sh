#!/bin/bash

ip address add 10.0.0.1/24 dev enp0s3
ip link set up dev enp0s3
