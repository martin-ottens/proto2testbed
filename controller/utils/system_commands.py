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

import subprocess
import pexpect
import re
import os
import shutil

from typing import List, Optional
from loguru import logger
from pathlib import Path


def get_asset_relative_to(base, file) -> str:
    return f"{Path(base).parent.resolve()}/{file}"


def log_trace(func):
    def wrap(*args, **kwargs):
        if args:
            if isinstance(args[0], str):
                cmd = re.sub(' +', ' ', args[0])
                logger.trace("Running command: " + cmd)
            elif isinstance(args[0], list):
                cmd = re.sub(' +', ' ', " ".join(args[0]))
                logger.trace("Running command: " + cmd)

        return func(*args, **kwargs)
    
    return wrap


@log_trace
def invoke_subprocess(command: List[str] | str, capture_output: bool = True, shell: bool = False, needs_root: bool = False) -> subprocess.CompletedProcess:
    needs_root = False if os.geteuid() == 0  else needs_root
    if isinstance(command, str) and needs_root:
        command = "sudo " + command
    elif isinstance(command, list) and needs_root:
        command = ["sudo"] + command
    
    return subprocess.run(command, capture_output=capture_output, shell=shell)


@log_trace
def invoke_pexpect(command: List[str] | str, timeout: int = None, encoding: str = "utf-8", needs_root: bool = False) -> pexpect.spawn:
    needs_root = False if os.geteuid() == 0  else needs_root
    if isinstance(command, str) and needs_root:
        command = "sudo " + command
    elif isinstance(command, list) and needs_root:
        command = ["sudo"] + command

    return pexpect.spawn(command, timeout=timeout, encoding=encoding)


def get_dns_resolver() -> str:
    pattern = re.compile(r'^(\d{1,3}\.){3}\d{1,3}$')
    process = invoke_subprocess(r"grep -oP '^\s*nameserver\s+\K\d{1,3}(\.\d{1,3}){3}' /etc/resolv.conf | head -n 1", shell=True, needs_root=False)

    if process.returncode != 0:
        raise Exception("Unable to get DNS resolver from /etc/resolv.conf")
    
    address = process.stdout.decode("utf-8")
    if address == "" or not pattern.match(address):
        raise Exception("Invalid results when getting DNS Resolver from /etc/resolv.conf - is an IPv4 resolver configured?")
    
    return address.replace("\n", "")


def set_owner(path: Path | str, owner: int) -> bool:
    proc = invoke_subprocess(["/usr/bin/chown", "-R", str(owner), str(path)], 
                                     capture_output=True, shell=False, needs_root=True)
    if proc.returncode != 0:
        logger.error(f"Error running chmod for {path}: {proc.stderr.decode('utf-8')}")
        return False
    
    return True


def copy_file_or_directory(source: Path, target: Path, executor: Optional[str] = None) -> bool:
    try:
        destination = target
        if target.is_dir():
            destination = target / Path(os.path.basename(source))

        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copy2(source, destination)

        logger.trace(f"Copied {'directory' if source.is_dir() else 'file'} from {source} to {destination}")

        if executor is not None:
            set_owner(destination, executor)

        return True
    except Exception as ex:
        logger.opt(exception=ex).error(f"Error while copying from '{source}' to '{target}'")
        return False


def rename_file_or_directory(file_or_directory: Path, new_name: str) -> bool:
    try:
        os.rename(file_or_directory, new_name)
        return True
    except Exception as ex:
        logger.opt(exception=ex).error(f"Error while renaming '{file_or_directory}' to '{new_name}'")
        return False


def remove_file_or_directory(to_delete: Path):
    try:
        if to_delete.is_dir():
            shutil.rmtree(to_delete, ignore_errors=True)
        else:
            os.remove(to_delete)
        
        return True
    except Exception as ex:
        logger.opt(exception=ex).error(f"Unable to delete '{to_delete}'")
        return False
