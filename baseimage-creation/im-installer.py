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

#!/usr/bin/python3

import pexpect
import argparse
import os
import sys
import time
import signal
import shutil

from typing import Optional, List
from pathlib import Path
from loguru import logger

import pexpect.expect

PEXPECT_TIMEOUT = 60
PEXPECT_VMNAME = "debian"
PEXPECT_ROOT_USER = "root"
PEXPECT_ROOT_PASSWD = "1"

QEMU_COMMAND_TEMPLATE = """qemu-system-x86_64 -m 1G -hda {image} \
                            {kvm} {dry} -boot c \
                            -nographic -serial mon:stdio \
                            -virtfs local,path={mount},mount_tag=host0,security_model=passthrough,id=host0"""

COMMANDS = {
    "prepare": "export DEBIAN_FRONTEND=noninteractive",
    "mount": "mount -t 9p -o trans=virtio host0 /mnt",
    "update": "apt-get update",
    "install": "apt-get reinstall -y /mnt/{package}",
    "shutdown": "shutdown now"
}


def create_qemu_command(image: Path, deb_path: str, 
                        disable_kvm: bool = False, dry_run: bool = False) -> str:
    return QEMU_COMMAND_TEMPLATE.format(
        image=str(image),
        mount=deb_path,
        kvm=('-enable-kvm -cpu host' if not disable_kvm else ''),
        dry=('-snapshot' if dry_run else '')
    )


def wait_for_shell_on_vm(proc: pexpect.spawn, timeout: int = PEXPECT_TIMEOUT):
    proc.expect(f"{PEXPECT_ROOT_USER}@{PEXPECT_VMNAME}:~#", timeout=timeout)


def run_one_command_on_vm(command: str, proc: pexpect.spawn, 
                          expected_rc: int = 0, timeout: int = PEXPECT_TIMEOUT) -> bool:
    logger.info(f"Exceuting command '{command}' on VM ...")
    proc.sendline(command)
    wait_for_shell_on_vm(proc, timeout=timeout)
    proc.sendline("echo $?")
    proc.readline()
    try:
        rc = int(proc.readline().strip().split("\r")[1])
    except Exception as _:
        rc = int(proc.readline().strip().split("\r")[1])
    wait_for_shell_on_vm(proc)
    if rc != expected_rc:
        logger.error(f"Command '{command}' finished with unexpected exit code: {rc} != {expected_rc}")
        return False
    else:
        logger.success(f"Sucessfully executed command '{command}'.")
        return True


def main(command: str, deb_file: str, extra: Optional[List[str]], 
         debug: bool = False, timeout: int = PEXPECT_TIMEOUT) -> bool:
    proc: pexpect.spawn
    with pexpect.spawn(command, timeout=timeout, encoding="utf-8") as proc:
        if debug:
            proc.logfile = sys.stdout

        try:
            # Skip GRUB Dialog
            wait_to = time.time() + timeout
            while True:
                if proc.expect([PEXPECT_VMNAME + " login:", pexpect.TIMEOUT], timeout=0.5) == 0:
                    break

                if wait_to < time.time():
                    raise pexpect.TIMEOUT("VM did not started in time!")

                proc.sendline("")


            proc.sendline(PEXPECT_ROOT_USER)
            proc.expect("Password:")
            proc.sendline(PEXPECT_ROOT_PASSWD)
            wait_for_shell_on_vm(proc)

            if not run_one_command_on_vm(COMMANDS["prepare"], proc, timeout=timeout):
                logger.critical("Unable to prepare for installation of instance-manager.deb package")
                proc.kill(signal.SIGTERM)
                return

            if not run_one_command_on_vm(COMMANDS["mount"], proc, timeout=timeout):
                logger.critical("Unable to mount instance-manager.deb package")
                proc.kill(signal.SIGTERM)
                return
            
            if not run_one_command_on_vm(COMMANDS["update"], proc, timeout=timeout):
                logger.critical("Unable to update apt packet sources")
                proc.kill(signal.SIGTERM)
                return

            if not run_one_command_on_vm(COMMANDS["install"].format(package=deb_file), 
                                         proc, timeout=2 * timeout):
                logger.critical("Unable to install instance-manager.deb package")
                proc.kill(signal.SIGTERM)
                return
            
            extra_error = False
            if extra is not None:
                for extra_command in extra:
                    extra_error = extra_error | (not run_one_command_on_vm(extra_command, proc, timeout=timeout))

            proc.sendline(COMMANDS["shutdown"])
            logger.info("Shutting down VM ... ")
            proc.expect(pexpect.EOF)
            logger.success("VM was shut down.")

            return not extra_error
        except pexpect.TIMEOUT as ex:
            logger.opt(exception=ex).critical("Timeout occured running command on VM!")
            proc.kill(signal.SIGTERM)
            sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="Serial QEMU Image Preparation Tool", 
                                     description="Install instance-manager.deb on a QEMU image and run additional commands")
    parser.add_argument("--input", "-i", required=True, type=str, 
                        help="Image Input path (will be modified when -o is omitted)")
    parser.add_argument("--package", "-p", required=True, type=str,
                        help="Path to the Instance Manager Debian Package installed during preparation")
    parser.add_argument("--output", "-o", required=False, type=str, default=None,
                        help="Output path for the modified image")
    parser.add_argument("--extra", "-e", type=str, required=False, default=None,
                        help="Extra commands to execute on VM during installation")
    parser.add_argument("--no_kvm", action="store_true", required=False, default=False,
                        help="Disable KVM virtualization")
    parser.add_argument("--debug", action="store_true", required=False, default=False,
                        help="Forward QEMU stdout and stderr")
    parser.add_argument("--dry_run", action="store_true", required=False, default=False,
                        help="Do not make any changes to the base image")
    parser.add_argument("--timeout", required=False, default=PEXPECT_TIMEOUT, type=int,
                        help="Base timeout for all commands")
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stdout, level="DEBUG", format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

    if args.extra is not None:
        logger.info(f"Running extra preparation commands from file '{args.extra}'")
        try:
            with open(args.extra, "r") as handle:
                extra_commands = handle.readlines()
            
            extra_commands = list(filter(lambda y: y != "", map(lambda x: x.strip(), extra_commands)))
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to load extra command file")
    else:
        extra_commands = None

    if args.dry_run:
        logger.warning("Dry run enabled, no persistent modifications to the image will be made")

    resolve_path = os.path.realpath(Path(args.package), strict=True)

    if not Path(resolve_path).exists():
        logger.critical(f"Instance Manager Package '{args.package}' could not be found.")
        sys.exit(1)

    resolve_path_parts = os.path.split(resolve_path)
    deb_path = resolve_path_parts[0]
    deb_file = resolve_path_parts[1]

    input_path = Path(args.input)

    if not input_path.exists():
        logger.critical(f"Imput Image '{args.input}' does not exist.")
        sys.exit(1)

    mod_path = input_path
    if args.output is not None:
        output_path = Path(args.output)
        mod_path = output_path
        logger.info(f"Copying Input Image '{input_path}' to '{output_path}'")
        try:
            shutil.copyfile(input_path, output_path)
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to copy image file.")
            sys.exit(1)
        logger.success(f"Image copied to '{output_path}', this image will be modified.")
    else:
        logger.info(f"Preparing Input Image '{input_path}' in place.")

    logger.info(f"Preparing QEMU Image '{mod_path}'")
    command = create_qemu_command(mod_path, deb_path, args.no_kvm, args.dry_run)
    try:
        if not main(command, deb_file, extra_commands, args.debug, args.timeout):
            logger.error("At least one extra command failed, image may be faulty.")
            sys.exit(2)
    except Exception as ex:
        logger.opt(exception=ex).critical("Unable to prepare image, image will be faulty.")
        sys.exit(1)

    logger.success("Image was prepared successfully.")
