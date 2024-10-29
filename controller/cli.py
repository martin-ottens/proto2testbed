import sys
import readline # Not unused, when imported, used by input()
import termios
import pexpect

from threading import Thread, Event
from loguru import logger

from utils.interfaces import Dismantable
from state_manager import MachineStateManager

class CLI(Dismantable):
    
    instance = None

    def _filter_logging(record):
        return CLI.instance.enable_output.is_set()

    def _enable_logging(self):
        logger.remove()
        if self.log_quiet:
            logger.add(sys.stdout, level="INFO", filter=CLI._filter_logging, colorize=True)
        elif self.log_verbose:
            logger.add(sys.stdout, level="TRACE", filter=CLI._filter_logging, colorize=True)
        else:
            logger.add(sys.stdout, level="DEBUG", filter=CLI._filter_logging, colorize=True)

    def _attach_to_tty(self, socket_path: str, name: str):
        process = pexpect.spawn("/usr/bin/socat", [f"UNIX-CONNECT:{socket_path}", "STDIO,raw,echo=0"], 
                            timeout=None, encoding="utf-8", echo=False)
        print(f"# Attached to Instance '{name}', CRTL + ] to disconnect.")
        process.send("\n")
        process.readline()
        process.interact()
        process.terminate()
        print("\n# Connection to serial TTY closed.")
        if process.isalive():
            logger.error("TTY attach scoat subprocess is still alive after termination!")

    def _run(self):
        def clear_stdin():
            termios.tcflush(sys.stdin, termios.TCIOFLUSH)

        while True:
            if not self.enable_interaction.is_set():
                self.enable_interaction.wait()
                clear_stdin()
            try:
                cli_input = input("> ")
                if not self.enable_interaction.is_set():
                    self.enable_interaction.wait()
                    clear_stdin()
                    continue
            except EOFError:
                continue
            
            parts = cli_input.strip().lower().split(" ", maxsplit=1)
            if len(parts) != 2:
                command, args = parts[0], None
            else:
                command, args = parts

            match command:
                case "continue" | "c":
                    if self.continue_event is None:
                        logger.error("Unable to continue testbed, continue_event object missing.")
                    else:
                        self.continue_event.set()
                    continue
                case "attach" | "a":
                    if args is None:
                        logger.error(f"No Instance Name given. Usage: {command} <Instance Name>")
                        continue

                    target = args.split(" ", maxsplit=1)[0]
                    machine = self.manager.get_machine(target)
                    if machine is None:
                        logger.error(f"Unable to get Instance with name '{machine}'")
                        continue
                    socket_path = machine.get_mgmt_tty_path()
                    if socket_path is None:
                        logger.error(f"Unable to get TTY Socket for Instance'{machine}'")
                        continue

                    self.toggle_output(False)
                    self._attach_to_tty(socket_path, target)
                    self.toggle_output(True)
                    logger.info("Resume with CLI after attachemend was terminated.")

                    continue
                case _:
                    logger.info(f"Unknown command '{command}', Available: continue, attach")

    def __init__(self, log_quiet: bool, log_verbose: bool, manager: MachineStateManager):
        CLI.instance = self
        self.manager = manager
        self.log_quiet = log_quiet
        self.log_verbose = log_verbose
        self.enable_interaction = Event()
        self.enable_output = Event()
        self.continue_event = None

        self.enable_interaction.clear()
        self.enable_output.set()
        self._enable_logging()

    def toggle_output(self, state: bool):
        if state:
            self.enable_output.set()
        else:
            self.enable_output.clear()

    def toggle_interaction(self, state: bool):
        if self.enable_interaction.is_set() and not state:
            sys.stdout.write("\033[2K\r") # Erase current line, carriage return

        if state:
            self.enable_interaction.set()
        else:
            self.enable_interaction.clear()

    def start_cli(self, event: Event):
        self.continue_event = event
        self.toggle_interaction(True)

    def stop_cli(self):
        self.continue_event = None
        self.toggle_interaction(False)

    def start(self):
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        pass

    def get_name(self) -> str:
        return "CLI Handler"

    def dismantle(self) -> None:
        self.stop()
