import sys
import readline # Not unused, when imported, used by input()
import time
import termios

from threading import Thread, Event
from loguru import logger

from utils.interfaces import Dismantable

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
            
            if cli_input.strip().lower() == "exit":
                print("Exiting...")
                break
            logger.info(f"cmd: " + cli_input.replace("\n", ""))

    def __init__(self, log_quiet: bool, log_verbose: bool):
        CLI.instance = self
        self.log_quiet = log_quiet
        self.log_verbose = log_verbose
        self.enable_interaction = Event()
        self.enable_output = Event()

        self.enable_interaction.clear()
        self.enable_output.set()
        self._enable_logging()

    def toggle_output(self, state: bool):
        if state:
            self.enable_logger.set()
        else:
            self.enable_logger.clear()

    def toggle_interaction(self, state: bool):
        if self.enable_interaction.is_set() and not state:
            sys.stdout.write("\033[2K\r") # Erase current line, carriage return

        if state:
            self.enable_interaction.set()
        else:
            self.enable_interaction.clear()

    def toogle_logging(self):
        time.sleep(5)
        logger.info("ON")
        self.toggle_interaction(True)
        time.sleep(20)
        self.toggle_interaction(False)
        logger.info("OFF")

    def start(self):
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()

        t1 = Thread(target=self.toogle_logging, daemon=True)
        t1.start()

    def stop(self):
        pass

    def get_name(self) -> str:
        return "CLI Handler"

    def dismantle(self) -> None:
        self.stop()
