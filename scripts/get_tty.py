#!/usr/bin/python3

import sys
import os
import pexpect

def main(socket_path: str):
    process = pexpect.spawn("/usr/bin/socat", [f"UNIX-CONNECT:{socket_path}", "STDIO,raw,echo=0"], 
                            timeout=None, encoding="utf-8", echo=False)
    process.send("\n")
    process.readline()
    process.interact()
    process.terminate()
    print("\n# Connection to serial TTY closed.")
    if process.isalive():
        print("scoat subprocess is still alive!")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage {sys.argv[0]} <vm-id>", file=sys.stderr)
        sys.exit(1)

    ids = sys.argv[1]

    socket_path = f"/tmp/testbed-{ids}/tty.sock"
    if not os.path.exists(socket_path):
        print(f"# Instance with ID '{ids}' does not exist.")
        sys.exit(1)

    print(f"# Attached to Instance '{ids}', CRTL + ] to disconnect.")
    main(socket_path)
