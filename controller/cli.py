import sys
import curses

from threading import Thread
from loguru import logger

from utils.interfaces import Dismantable

class CLI(Dismantable):

    instance = None
    logger_enabled: bool = True

    def _filter_logging(record):
        return CLI.logger_enabled
    
    def _log_sink(text):
        win = CLI.instance.output_win
        if len(text) > win.getmaxyx()[1]:
            text = text[-win.getmaxyx()[1]:]
        win.addstr(text)
        win.refresh()

    def _enable_logging(self):
        logger.remove()
        if self.log_quiet:
            logger.add(CLI._log_sink, level="INFO", filter=CLI._filter_logging, colorize=True)
        elif self.log_verbose:
            logger.add(CLI._log_sink, level="TRACE", filter=CLI._filter_logging, colorize=True)
        else:
            logger.add(CLI._log_sink, level="DEBUG", filter=CLI._filter_logging, colorize=True)

    def _run(self):
        while True:
            self.input_win.clear()
            self.input_win.addstr(0, 0, "> ")
            self.input_win.refresh()

            cli_input = self.input_win.getstr().decode('utf-8')
            if cli_input.strip().lower() == "exit":
                print("Exiting...")
                break
            logger.info(f"You entered: " + cli_input.replace("\n", ""))

    def __init__(self, log_quiet: bool, log_verbose: bool):
        if CLI.instance is None:
            CLI.instance = self

        self.log_quiet = log_quiet
        self.log_verbose = log_verbose
        self.logging_enabled = True
        self._enable_logging()

    def run_wrapper(self, stdscr):
        curses.curs_set(1)
        stdscr.clear()
        stdscr.refresh()
        height, width = stdscr.getmaxyx()

        self.output_win = stdscr.subwin(height - 1, width, 0, 0)
        self.output_win.scrollok(True) 
        self.input_win = stdscr.subwin(1, width, height - 1, 0)
        self.input_win.clear()

    def start(self):
        curses.wrapper(self.run_wrapper)
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        pass

    def get_name(self) -> str:
        return "CLI Handler"

    def dismantle(self) -> None:
        self.stop()