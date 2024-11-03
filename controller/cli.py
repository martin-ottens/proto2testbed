import sys
import readline # Not unused, when imported, used by input()
import termios
import pexpect

from threading import Thread, Event
from loguru import logger
from typing import Optional, List
from pathlib import Path

from utils.interfaces import Dismantable
from utils.continue_mode import *
from state_manager import MachineStateManager
from utils.settings import SettingsWrapper

class CLI(Dismantable):
    _CLEAN_LOG_FORMAT = "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
    instance = None

    def setup_early_logging():
        logger.remove()
        logger.add(sys.stdout, level="DEBUG", format=CLI._CLEAN_LOG_FORMAT)

    def _filter_logging(record):
        return CLI.instance.enable_output.is_set()

    def _enable_logging(self):
        logger.level(name="CLI", no=45, color="<magenta>")
        logger.remove()
        if self.log_quiet:
            logger.add(sys.stdout, level="INFO", 
                       format=CLI._CLEAN_LOG_FORMAT,
                       filter=CLI._filter_logging)
        elif self.log_verbose:
            logger.add(sys.stdout, level="TRACE", 
                       filter=CLI._filter_logging)
        else:
            logger.add(sys.stdout, level="DEBUG", 
                       filter=CLI._filter_logging, 
                       format=CLI._CLEAN_LOG_FORMAT)

    def _attach_to_tty(self, socket_path: str):
        process = pexpect.spawn("/usr/bin/socat", [f"UNIX-CONNECT:{socket_path}", "STDIO,raw,echo=0"], 
                            timeout=None, encoding="utf-8", echo=False)
        process.send("\n")
        process.readline()
        process.interact()
        process.terminate()
        print("\n")
        if process.isalive():
            logger.error("TTY attach scoat subprocess is still alive after termination!")

    def handle_command(self, base_command: str, args: Optional[List[str]]) -> bool:
        match base_command:
            case "continue" | "c":
                continue_to = PauseAfterSteps.DISABLE
                if args is not None and len(args) >= 1:
                    try:
                        continue_to = PauseAfterSteps[args[0].upper()]
                    except Exception:
                        logger.log("CLI", f"Can't continue to '{args[0]}': State not INIT OR EXPERIMENT")
                        return True
        
                if self.continue_event is None:
                    logger.log("CLI", "Unable to continue testbed, continue_event object missing.")
                    return True
                else:
                    if not self.continue_mode.update(ContinueMode.CONTINUE_TO, continue_to):
                        logger.log("CLI", f"Can't continue to '{args[0]}': Step is in the past.")
                        return True
                    
                    logger.log("CLI", f"Continue with testbed execution. Interaction will be disabled.")
                    self.continue_event.set()
                    return True
            case "attach" | "a":
                if args is None or len(args) < 1:
                    logger.log("CLI", f"No Instance name provided. Usage: {base_command} <Instance Name>")
                    return True
                target = args[0]
                machine = self.manager.get_machine(target)
                if machine is None:
                    logger.log("CLI", f"Unable to get Instance with name '{machine}'")
                    return True
                socket_path = machine.get_mgmt_tty_path()
                if socket_path is None:
                    logger.log("CLI", f"Unable to get TTY Socket for Instance'{machine}'")
                    return True
                logger.log("CLI", f"Attaching to Instance '{target}', CRTL + ] to disconnect.")
                self.toggle_output(False)
                self._attach_to_tty(socket_path)
                self.toggle_output(True)
                logger.log("CLI", f"Connection to serial TTY of Instance '{target}' closed.")
                return True
            case "copy" | "cp":
                if args is None or len(args) < 2:
                    logger.log("CLI", f"No source and/or destination provided. Usage {base_command} (<From Instance>:)<From Path> (<To Instance>:)<To Path>")
                    return True
                
                source_str = args[0]
                destination_str = args[1]

                if len(list(filter(lambda x: ":" in x, [source_str, destination_str]))) != 1:
                    logger.log("CLI", f"Cannot copy from Instance to Instance or Host to Host. Host -> Instance or Instance -> Host possible.")
                    return True
                
                source_path = None
                destination_path = None
                instance = None
                copy_to_instance = False

                if ":" in source_str:
                    instance, source_path = source_str.split(":", maxsplit=1)
                    copy_to_instance = False
                else:
                    source_path = source_str
                
                if ":" in destination_str:
                    instance, destination_path = destination_str.split(":", maxsplit=1)
                    copy_to_instance = True
                else:
                    destination_path = destination_str

                if instance is None:
                    raise Exception("Instance not given after parsing.")
                
                machine = self.manager.get_machine(instance)
                if machine is None:
                    logger.log("CLI", f"Unable to get Instance with name '{instance}'")
                    return True

                status, message = machine.file_copy_helper.copy(Path(source_path), 
                                                                Path(destination_path), 
                                                                copy_to_instance)
                if not status:
                    logger.log("CLI", message)

                return True
            case "preserve" | "p":
                if args is None or len(args) < 2:
                    logger.log("CLI", f"No Instance name or path provided. Usage: {base_command} <Instance Name> <Path>")
                    return True
                target = args[0]
                machine = self.manager.get_machine(target)
                if machine is None:
                    logger.log("CLI", f"Unable to get Instance with name '{machine}'")
                    return True
                
                if SettingsWrapper.cli_paramaters.preserve is None:
                    logger.log("CLI", f"File preservation is not enabled in this testbed run.")
                    return True
                
                machine.add_preserve_file(args[1])
                logger.log("CLI", f"File '{args[1]}' was as added to preserve list of Instance '{target}'")
                return True
            case "list" | "ls":
                for machine in self.manager.get_all_machines():
                    line = f"- Instance '{machine.name}' ({machine.uuid}) | {machine.get_state().name}"
                    if len(machine.interfaces_hostside) != 0:
                        line += f" | Interfaces: {', '.join(machine.interfaces_hostside)}"
                    if machine.mgmt_ip_addr is not None:
                        line += f" | MGMT IP: {machine.mgmt_ip_addr}"
                    logger.log("CLI", line)
                return True
            case "exit" | "e":
                self.continue_mode.update(ContinueMode.EXIT)
                if self.continue_event is None:
                    logger.log("CLI", "Unable to exit testbed, continue_event object missing.")
                    return True
                else:
                    logger.log("CLI", f"Shutting down testbed. Interaction will be disabled.")
                    self.continue_event.set()
                    return True
            case "help" | "h":
                logger.opt(ansi=True).log("CLI", "--------- Proto²Testbed Interactive Mode Help ---------")
                logger.opt(ansi=True).log("CLI", "  <u>c</u>ontinue (INIT|EXPERIMENT) -> Continue testbed (to next pause step)", color=True)
                logger.opt(ansi=True).log("CLI", "  <u>a</u>ttach \<Instance>          -> Attach to TTY of an Instance", color=True)
                logger.opt(ansi=True).log("CLI", "  <u>c</u>o<u>p</u>y (\<Instance>:)\<Path> (\<Instance>:)\Path -> Copy files from/to instance", color=True)
                logger.opt(ansi=True).log("CLI", "  <u>l</u>i<u>s</u>t                      -> List all Instances in testbed", color=True)
                logger.opt(ansi=True).log("CLI", "  <u>p</u>reserve \<Instance>:\<Path> -> Mark file or directory for preservation", color=True)
                logger.opt(ansi=True).log("CLI", "  <u>e</u>xit                       -> Terminate Testbed", color=True)
                logger.opt(ansi=True).log("CLI", "  <u>h</u>elp                       -> Show this help", color=True)
                logger.opt(ansi=True).log("CLI", "------------------------------------------------------")
                return True
            case _:
                return False

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
                args = args.split(" ")
            
            status = False
            try:
                status = self.handle_command(command, args)
            except Exception as ex:
                status = False
                logger.opt(exception=ex).error("Error running command")
            
            if not status:
                logger.log("CLI", f"Unknown command '{command}' or error running it, use 'help' to show available commands.")


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

    def start_cli(self, event: Event, continue_mode: CLIContinue):
        self.continue_event = event
        self.continue_mode = continue_mode
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
