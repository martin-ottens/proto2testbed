#!/bin/bash
#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2024-2025 Martin Ottens
# 
# This program is free software: you can redistribute it and/or modify 
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful, 
# but WITHOUT ANY WARRANTY; without even the implied warranty of 
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the 
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License 
# along with this program. If not, see https://www.gnu.org/licenses/.
#

# Proto²Testbed Installer Script for Debian 12 and 13
# 
# 1. -> Clone the repo to /opt/proto-testbed
# 2. -> Run the script as root from within this directory
#

# Bash strict mode.
set -euo pipefail
IFS=$'\n\t'

if [[ -f /etc/os-release ]]; then
    source /etc/os-release

    if [[ "$ID" != "debian" || ("$VERSION_ID" != "12" && "$VERSION_ID" != "13")]]; then
        echo "OS Release is not Debian 12 or 13, installer not compatible." >&2
        exit 1
    fi
else
    echo "Unable to query /etc/os-release, can't verify Debian version." >&2
    exit 1
fi

if [[ "$PWD" != "/opt/proto-testbed" ]]; then
    echo "Working direcory must be /opt/proto-testbed. Please check." >&2
    exit 1
fi

if [[ "$EUID" -ne 0 ]]; then
    echo "Script must be run as root user (e.g. via sudo)" >&2
    exit 1
fi

echo "Installing required dependencies ..."
apt-get install -y --no-install-recommends qemu-utils qemu-system-x86 qemu-system-gui bridge-utils iptables net-tools genisoimage python3 iproute2 influxdb influxdb-client make socat

echo "Installing required Python dependencies from Debian packages ..."
apt-get install -y --no-install-recommends python3-jinja2 python3-pexpect python3-loguru python3-jsonschema python3-influxdb python3-psutil python3-networkx python3-jsonpickle python3-filelock
apt-get install -y --no-install-recommends python3-numpy python3-matplotlib

echo "Setting up default InfluxDB database ..."
influx -execute 'CREATE DATABASE testbed'

echo "Setting up default configs ..."
chmod go+r -R /opt/proto-testbed
mkdir -p -m 755 /etc/proto2testbed
cp proto2testbed_defaults.json /etc/proto2testbed/.
chmod 744 /etc/proto2testbed/*

if [[ ! -f "/dev/vsock" ]]; then
    read -r -p "Enable VSOCK support by loading kernel modules? (y/N): " response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        modprobe vhost_vsock
        echo "vhost_vsock" >> /etc/modules
    else
        sed -i 's/"enable_vsock": true,/"enable_vsock": false,/' /etc/proto2testbed/proto2testbed_defaults.json
    fi
fi

read -r -p "Link scripts and programs? (y/N): " response

if [[ "$response" =~ ^[Yy]$ ]]; then
    ln -s /opt/proto-testbed/proto-testbed /usr/local/bin/p2t
    ln -s /opt/proto-testbed/baseimage-creation/im-installer.py /usr/local/bin/p2t-genimg
fi
    
echo "Installation finished!"
exit 0
