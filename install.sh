#!/bin/bash

# Proto²Testbed Installer Script for Debian 12
# 
# 1. -> Clone the repo to /opt/proto-testbed
# 2. -> Run the script as root from within this directory
#

if [[ -f /etc/os-release ]]; then
    source /etc/os-release

    if [[ "$ID" != "debian" || "$VERSION_ID" != "12" ]]; then
        echo "OS Release is not Debian 12, installer not compatible." >&2
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
apt install -y qemu-utils qemu-system-x86 qemu-system-gui bridge-utils iptables net-tools genisoimage python3 iproute2 influxdb influxdb-client make socat

echo "Installing required Python dependencies from Debian packages ..."
apt install -y python3-jinja2 python3-pexpect python3-loguru python3-jsonschema python3-influxdb python3-psutil
apt install -y python3-numpy python3-matplotlib

echo "Setting up default InfluxDB database ..."
influx -execute 'CREATE DATABASE testbed'

echo "Setting up default configs ..."
chmod go+r -R /opt/proto-testbed
mkdir -p -m 774 /etc/proto2testbed
cp proto2testbed_defaults.json /etc/proto2testbed/.
chmod 774 /etc/proto2testbed/*

read -r -p "Link scripts and programs? (y/N): " response
    
if [[ "$response" =~ ^[Yy]$ ]]; then
    ln -s /opt/proto-testbed/proto-testbed /usr/local/bin/p2t
    ln -s /opt/proto-testbed/scripts/get_tty.py /usr/local/bin/p2t-tty
    ln -s /opt/proto-testbed/scripts/image_creator.py /usr/local/bin/p2t-genimg
fi
    
echo "Installation finished!"
exit 0
