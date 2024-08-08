import subprocess
import pexpect

from typing import List
from loguru import logger
from pathlib import Path

def get_asset_relative_to(base, file) -> str:
    return f"{Path(base).parent.resolve()}/{file}"


def log_trace(func):
    def wrap(*args, **kwargs):
        if args:
            if isinstance(args[0], str):
                logger.trace("Running command:" + args[0])
            elif isinstance(args[0], list):
                logger.trace("Running command:" + " ".join(args[0]))

        return func(*args, **kwargs)
    
    return wrap


@log_trace
def invoke_subprocess(command: List[str] | str, capture_output: bool = True, shell: bool = False, needs_root: bool = False) -> subprocess.CompletedProcess:
    if isinstance(command, str) and needs_root:
        command = "sudo " + command
    elif isinstance(command, list) and needs_root:
        command = ["sudo"] + command
    
    return subprocess.run(command, capture_output=capture_output, shell=shell)

@log_trace
def invoke_pexpect(command: List[str] | str, timeout: int = None, encoding: str = "utf-8", needs_root: bool = False) -> pexpect.spawn:
    if isinstance(command, str) and needs_root:
        command = "sudo " + command
    elif isinstance(command, list) and needs_root:
        command = ["sudo"] + command

    return pexpect.spawn(command, timeout=timeout, encoding=encoding)