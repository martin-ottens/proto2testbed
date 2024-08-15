#!/usr/bin/python3

import pexpect
import argparse
import os
import sys
import time
import signal

from typing import Optional, List
from pathlib import Path
from loguru import logger

import pexpect.expect

PEXPECT_TIMEOUT = 30
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
    "install": "apt-get install -y /mnt/{package}",
    "shutdown": "shutdown now"
}


def create_qemu_command(image: str, deb_path: str, 
                        disable_kvm: bool = False, dry_run: bool = False) -> str:
    return QEMU_COMMAND_TEMPLATE.format(
        image=image,
        mount=deb_path,
        kvm=('-enable-kvm -cpu host' if not disable_kvm else ''),
        dry=('-snapshot' if dry_run else '')
    )


def wait_for_shell_on_vm(proc: pexpect.spawn, timeout: int = PEXPECT_TIMEOUT):
    proc.expect(f"{PEXPECT_ROOT_USER}@{PEXPECT_VMNAME}:~#", timeout=timeout)


def run_one_command_on_vm(command: str, proc: pexpect.spawn, 
                          expected_rc: int = 0, timeout: int = PEXPECT_TIMEOUT) -> bool:
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
        logger.success(f"Command '{command}' was executed on VM.")
        return True


def main(command: str, deb_file: str, extra: Optional[List[str]], debug: bool = False) -> bool:
    proc: pexpect.spawn
    with pexpect.spawn(command, timeout=PEXPECT_TIMEOUT, encoding="utf-8") as proc:
        if debug:
            proc.logfile = sys.stdout

        try:
            # Skip GRUB Dialog
            wait_to = time.time() + PEXPECT_TIMEOUT
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

            if not run_one_command_on_vm(COMMANDS["prepare"], proc):
                logger.critical("Unable to prepare for installation of instance-manager.deb package")
                proc.kill(signal.SIGTERM)
                return

            if not run_one_command_on_vm(COMMANDS["mount"], proc):
                logger.critical("Unable to mount instance-manager.deb package")
                proc.kill(signal.SIGTERM)
                return

            if not run_one_command_on_vm(COMMANDS["install"].format(package=deb_file), 
                                         proc, timeout=2 * PEXPECT_TIMEOUT):
                logger.critical("Unable to install instance-manager.deb package")
                proc.kill(signal.SIGTERM)
                return
            
            extra_error = False
            if extra is not None:
                for extra_command in extra:
                    extra_error = extra_error | run_one_command_on_vm(extra_command, proc)

            proc.sendline(COMMANDS["shutdown"])
            logger.info("Shutting down VM ... ")
            proc.expect(pexpect.EOF)
            logger.success("VM was shut down.")

            return extra_error
        except pexpect.TIMEOUT as ex:
            logger.opt(exception=ex).critical("Timeout occured running command on VM!")
            proc.kill(signal.SIGTERM)
            sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="Serial QEMU Image Preparation Tool", 
                                     description="Install instance-manager.deb on a QEMU image and run additional commands")
    parser.add_argument("IMAGE", type=str, help="Installation QEMU image")
    parser.add_argument("PACKAGE", type=str, help="Path to instance-manager Debian package")
    parser.add_argument("--extra", "-e", type=str, required=False, default=None,
                        help="Extra commands to execute on VM during installation")
    parser.add_argument("--no_kvm", action="store_true", required=False, default=False,
                        help="Disable KVM virtualization")
    parser.add_argument("--debug", "-d", action="store_true", required=False, default=False,
                        help="Forward QEMU stdout and stderr")
    parser.add_argument("--dry_run", "-0", action="store_true", required=False, default=False,
                        help="Do not make any changes to the base image")
    args = parser.parse_args()

    logger.info(f"Preparing QEMU image {args.IMAGE}")

    if args.extra is not None:
        logger.info(f"Running extra preparation commands from file {args.extra}")
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

    resolve_path = os.path.realpath(Path(args.PACKAGE), strict=True)
    resolve_path_parts = os.path.split(resolve_path)
    deb_path = resolve_path_parts[0]
    deb_file = resolve_path_parts[1]

    command = create_qemu_command(args.IMAGE, deb_path, args.no_kvm, args.dry_run)
    try:
        if not main(command, deb_file, extra_commands, args.debug):
            logger.error("At least one extra command failed, image may be faulty.")
            sys.exit(2)
    except Exception as ex:
        logger.opt(exception=ex).critical("Unable to prepare image, image will be faulty.")
        sys.exit(1)

    logger.success("Image was prepared successfully.")
