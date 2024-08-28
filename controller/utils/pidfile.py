import atexit
import psutil
import os

from typing import Optional

class PidFile():
    def __init__(self, file: str, name: Optional[str] = None) -> None:
        self.file: str = file
        self.name = name
        self.pid: str = os.getpid()

    def delete_pidfile(self) -> None:
        if os.path.exists(self.file):
            try: os.unlink(self.file)
            except Exception:
                pass

    def old_running(self) -> bool:
        old_pid = 0
        if os.path.exists(self.file):
            try:
                with open(self.file, "r") as handle:
                    old_pid = int(handle.read())
            except Exception:
                self.delete_pidfile()
                return False
            
        if not psutil.pid_exists(old_pid):
            self.delete_pidfile()
            return False
        
        if self.name is not None:
            try:
                old_cmdline = psutil.Process(old_pid).cmdline()[0]
                if self.name in old_cmdline:
                    return True
                else:
                    self.delete_pidfile()
                    return False
            except Exception:
                pass
        
        return True

    def __enter__(self):
        if self.old_running():
            raise Exception("Other process is still running!")
        
        with open(self.file, "w") as handle:
            handle.write(str(os.getpid()))

        atexit.register(self.delete_pidfile)
        return self
    
    def __exit__(self, *_) -> None:
        self.delete_pidfile()
        atexit.unregister(self.delete_pidfile)
        pass
