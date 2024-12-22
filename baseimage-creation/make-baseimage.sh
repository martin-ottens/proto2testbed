#!/bin/bash
#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2024 Martin Ottens
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


# Proto²Testbed Base Image Creation Script
# 
# This script installes a Debian 12 amd64 OS to a base diskimage in a fully 
# automated way.

# Bash strict mode.
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

usage() {
  echo "Usage: $0 <OS NETINSTALL ISO> <BASEIMAGE OUTPUT NAME>"
  echo
  echo "Arguments:"
  echo "  <OS NETINSTALL ISO>     Path to the downloaded Debain 12 ISO"
  echo "  <BASEIMAGE OUTPUT NAME> Path to the output baseimage file (overwrites existing)"
  echo
  echo "Options:"
  echo "  --size <size>           Optional size for the baseimage file (default: 4G)"
  echo "  --help                  Show this help"
  echo
  echo "Example:"
  echo "  $0 ~/debian-12.8.0-amd64-netinst.iso /images/debian.qcow2 --size 4G"
  exit 1
}

cleanup() {
  TEST_TEMPDIR=${TEMP_DIR:-}

  if [ -z ${TEST_TEMPDIR} ]; then 
    echo "No tempdir was creating, nothing to clean up."
  else
    if mountpoint -q "$TEMP_DIR/usb"; then
        umount $TEMP_DIR/usb
    fi
    if mountpoint -q "$TEMP_DIR/iso"; then
        umount $TEMP_DIR/iso
    fi
    if [ -d "$TEMP_DIR" ]; then
        rm -rf $TEMP_DIR
    fi
    echo "Cleanup completed."
  fi
}

if [[ "$EUID" -ne 0 ]]; then
    echo "Error: Script must be run as root user (e.g. via sudo)" >&2
    exit 1
fi

SIZE="4G"
POSITIONAL=()
while [[ $# -gt 0 ]]; do
  case $1 in
    --size)
      SIZE="$2"
      shift # arg for --size
      shift # value for --size
      ;;
    -h|--help)
      usage
      ;;
    --*)
      echo "Error: Unknown option $1"
      usage
      ;;
    *)
      POSITIONAL+=("$1")
      shift
      ;;
  esac
done

set -- "${POSITIONAL[@]}"

if [ "$#" -ne 2 ]; then
  echo "Error: Invalid number of arguments."
  usage
fi

ISO_PATH="$1"
QCOW2_PATH="$2"

if [ ! -f "$ISO_PATH" ]; then
  echo "Error: The iso file '$ISO_PATH' does not exist."
  exit 1
fi

QCOW2_DIR="$(dirname "$QCOW2_PATH")"
if [ ! -d "$QCOW2_DIR" ]; then
  echo "Error: The directory '$QCOW2_DIR' does not exist."
  exit 1
fi

if [[ "$ISO_PATH" != *.iso ]]; then
  echo "Error: The input iso file must have a .iso extension (other formats are not supported)."
  exit 1
fi

if [[ "$QCOW2_PATH" != *.qcow2 ]]; then
  echo "Error: The baseimage output file must have a .qcow2 extension."
  exit 1
fi

# Enable cleanup handler before creating anything on disk
trap cleanup EXIT

TEMP_DIR="$(mktemp -d)"
echo "Temporary directory created at '$TEMP_DIR'"

mkdir -p $TEMP_DIR/usb
mkdir -p $TEMP_DIR/iso
dd if=/dev/zero of=$TEMP_DIR/preseed.img bs=4M count=10 > /dev/null
mkfs.vfat $TEMP_DIR/preseed.img || { echo "Error: Creation of pressed USB image failed."; exit 1; }

echo "Mounting ISO file..."
mount -r -o loop $ISO_PATH $TEMP_DIR/iso || { echo "Error: Failed to mount ISO."; exit 1; }

echo "Mounting USB directory..."
mount -o loop $TEMP_DIR/preseed.img $TEMP_DIR/usb || { echo "Error: Failed to mount preseed USB directory."; exit 1; }

cp $SCRIPT_DIR/preseed.cfg $TEMP_DIR/usb/.
umount $TEMP_DIR/usb

echo "Creating baseimage to '$QCOW2_PATH' with size '$SIZE'..."
qemu-img create -f qcow2 $QCOW2_PATH $SIZE || { echo "Error: Unable to run qemu-img create."; exit 1; }

echo "Installing '$ISO_PATH' to '$QCOW2_PATH' ..."
qemu-system-x86_64 -m 1G -hda $QCOW2_PATH \
        -cdrom $ISO_PATH -boot d \
        -nographic -serial mon:stdio \
        -kernel $TEMP_DIR/iso/install.amd/vmlinuz \
        -initrd $TEMP_DIR/iso/install.amd/initrd.gz \
        -drive file=$TEMP_DIR/preseed.img,format=raw,if=virtio \
        -enable-kvm -cpu host -no-reboot \
        -append "console=ttyS0,115200n8 auto=true priority=critical preseed/file=/media/preseed.cfg"

echo "Installation completed successfully."
