# This file is part of Proto²Testbed.
#
# Copyright (C) 2026 Martin Ottens
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
import threading

from typing import List, Optional

class LogStreamer:
    def __init__(self, stdout_log_fn, stderr_log_fn):
        self.stdout = stdout_log_fn
        self.stderr = stderr_log_fn

    def run_and_stream(self, command: str | List[str], shell: bool = False, 
                       timeout: Optional[int] = None) -> int:
        def single_line_reader(pipe, log_fn):
            if log_fn is None:
                return

            for line in iter(pipe.readline, ""):
                log_fn(line.rstrip())
            pipe.close()

        proc = subprocess.Popen(command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            shell=shell
        )

        stdout_thread = threading.Thread(target=single_line_reader, 
                                         args=(proc.stdout, self.stdout,))
        stderr_thread = threading.Thread(target=single_line_reader, 
                                         args=(proc.stderr, self.stderr,))
        stdout_thread.start()
        stderr_thread.start()

        try:
            proc.wait(timeout=timeout)
        except Exception as ex:
            raise ex
        finally:
            stdout_thread.join()
            stderr_thread.join()

        return proc.returncode
