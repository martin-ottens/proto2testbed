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

import sys
import readline # Not unused, when imported, used by input()
import termios
import pexpect

from threading import Thread, Event, Lock
from loguru import logger
from typing import Optional, List
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime

from utils.interfaces import Dismantable
from utils.continue_mode import *
from common.instance_manager_message import NullMessageUpstream


@dataclass
class GeneralLogEntry:
    message: str
    level: str
    at: datetime

class CLI(Dismantable):
    _CLEAN_LOG_FORMAT = "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"

    @staticmethod
    def setup_early_logging():
        logger.remove()
        logger.add(sys.stdout, level="DEBUG", format=CLI._CLEAN_LOG_FORMAT)

    def _enable_logging(self):
        def filter_logging_scoped(record):
            if self.log_to_storage:
                if self.full_result_wrapper is not None:
                    self.full_result_wrapper.append_controller_log(message=record["message"],
                                                              level=record["level"].name,
                                                              time=record["time"])
                return False

            return self.enable_output.is_set()

        try:
            logger.level(name="CLI", no=45, color="<magenta>")
        except Exception:
            pass

        logger.remove()
        if self.provider.log_verbose == 0:
            logger.add(sys.stdout, level="INFO", 
                       format=CLI._CLEAN_LOG_FORMAT,
                       filter=filter_logging_scoped)
        elif self.provider.log_verbose == 1:
            logger.add(sys.stdout, level="DEBUG", 
                       filter=filter_logging_scoped, 
                       format=CLI._CLEAN_LOG_FORMAT)
        else:
            logger.add(sys.stdout, level="TRACE", 
                       filter=filter_logging_scoped)

    def __init__(self, provider) -> None:
        self.provider = provider
        self.provider.set_cli(self)
        self.enable_interaction = Event()
        self.enable_output = Event()
        self.continue_event = None
        self.signal_lock = Lock()
        self.kill_input = Event()
        self.kill_input.clear()
        self.log_to_storage = self.provider.from_api_call
        self.full_result_wrapper = None

        self.enable_interaction.clear()
        self.enable_output.set()
        self._enable_logging()

    def attach_to_tty(self, socket_path: str):
        process = pexpect.spawn("/usr/bin/socat", [f"UNIX-CONNECT:{socket_path}", "STDIO,raw,echo=0"], 
                            timeout=None, encoding="utf-8", echo=False)
        process.send("\n")
        process.readline()
        process.interact()
        process.terminate()
        if process.isalive():
            logger.error("TTY attach scoat subprocess is still alive after termination!")

    def attach_to_ssh(self, conn: str):
        process = pexpect.spawn("/usr/bin/ssh", ["-o", "StrictHostKeyChecking=no", "-o", 
                                                 "LogLevel=ERROR", "-o", "UserKnownHostsFile=/dev/null", conn])
        process.interact()
        process.terminate()
        print("\n")
        if process.isalive():
            logger.error("SSH subprocess is still alive after termination!")

    def handle_command(self, base_command: str, args: Optional[List[str]]) -> bool:
        match base_command:
            case "restore" | "r":
                if not self.provider.snapshots_enabled:
                    logger.log("CLI", "Checkpoints are not enabled or available.")
                    return True
                
                self.provider.instance_manager.reset_all_after_snapshot_restore()
                self.provider.instance_manager.do_for_all_instances_parallel(lambda instance: instance.prepare_reconnect())
                
                def restore_snapsnot_callback(instance) -> bool:
                    if instance.instance_helper is None:
                        logger.critical("Unable to restore checkpoints: No instance helper available.")
                        return False
                    
                    return instance.instance_helper.restore_snapshot()
                
                if self.provider.instance_manager.do_for_all_instances_parallel(restore_snapsnot_callback):
                    self.provider.instance_manager.do_for_all_instances_parallel(lambda instance: 
                                                                 instance.send_message(NullMessageUpstream(False)))

                    logger.log("CLI", "Checkpoints from INIT stage restored for all Instances.")
                else:
                    logger.log("CLI", "Unable to restore all checkpoints.")
                return True

            case "set" | "s":
                def set_usage():
                    logger.opt(ansi=True).log("CLI", "Usage: <u>s</u>et \<Parameter> \<Value>, with Parameters:", color=True)
                    logger.opt(ansi=True).log("CLI", " - preserve:   Update preserve path, skip value to disable", color=True)
                    logger.opt(ansi=True).log("CLI", " - experiment: Update experiment tag (for InfluxDB storage)", color=True)

                if args is None or len(args) < 1:
                    set_usage()
                    return True
                
                match args[0].lower():
                    case "preserve":
                        preserve_file = None
                        if len(args) >= 2:
                            preserve_file = Path(args[1])
                        
                        if not self.provider.update_preserve_path(preserve_file):
                            logger.log("CLI", "Unable to update file preservation path")
                        else:
                            logger.log("CLI", "File preservation path successfully updated")
                    case "experiment":
                        if len(args) < 2:
                            set_usage()
                            return True

                        experiment = args[1]

                        try:
                            self.provider.update_experiment_tag(experiment, True)
                            logger.log("CLI", f"Experiment tag sucessfully changed to '{experiment}'")
                        except Exception as ex:
                            logger.opt(exception=ex).log("CLI", "Unable to update experiment tag.")
                    case _:
                        set_usage()
                    
                return True

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
                        logger.log("CLI", f"Can't continue to '{continue_to}': Step is in the past.")
                        return True
                    
                    logger.log("CLI", f"Continue with testbed execution. Interaction will be disabled.")
                    self.continue_event.set()
                    return True

            case "attach" | "a":
                if args is None or len(args) < 1:
                    logger.log("CLI", f"No Instance name provided. Usage: {base_command} <Instance Name>")
                    return True
                
                if self.provider.instance_manager is None:
                    logger.log("CLI", f"No Instances available to attach to.")
                    return True
                
                target = args[0]
                instance = self.provider.instance_manager.get_instance(target)
                if instance is None:
                    logger.log("CLI", f"Unable to get Instance with name '{instance}'")
                    return True
                socket_path = instance.get_mgmt_tty_path()
                if socket_path is None:
                    logger.log("CLI", f"Unable to get TTY Socket for Instance'{instance}'")
                    return True
                logger.log("CLI", f"Attaching to Instance '{target}', CRTL + ] to disconnect.")
                self.toggle_output(False)
                self.attach_to_tty(socket_path)
                self.toggle_output(True)
                logger.log("CLI", f"Connection to serial TTY of Instance '{target}' closed.")
                return True

            case "copy" | "cp":
                if args is None or len(args) < 2:
                    logger.log("CLI", f"No source and/or destination provided. Usage {base_command} (<From Instance>:)<From Path> (<To Instance>:)<To Path>")
                    return True
                
                if self.provider.instance_manager is None:
                    logger.log("CLI", f"No Instances available to perform copy.")
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
                    source_path = Path(source_path)
                    copy_to_instance = False
                else:
                    source_path = Path(source_str)
                
                if ":" in destination_str:
                    instance, destination_path = destination_str.split(":", maxsplit=1)
                    destination_path = Path(destination_path)
                    copy_to_instance = True
                else:
                    destination_path = Path(destination_str)

                if not source_path.is_absolute() or not destination_path.is_absolute():
                    logger.log("CLI", "Source and destination paths must be absolute.")
                    return True

                if instance is None:
                    raise Exception("Instance not given after parsing.")
                
                instance = self.provider.instance_manager.get_instance(instance)
                if instance is None:
                    logger.log("CLI", f"Unable to get Instance with name '{instance}'")
                    return True

                status, message = instance.file_copy_helper.copy(source_path, 
                                                                destination_path, 
                                                                copy_to_instance)
                if not status:
                    logger.log("CLI", message)

                return True

            case "preserve" | "p":
                if args is None or len(args) < 2:
                    logger.log("CLI", f"No Instance name or path provided. Usage: {base_command} <Instance Name> <Path>")
                    return True
                
                if self.provider.instance_manager is None:
                    logger.log("CLI", f"No Instances available to preserve files from.")
                    return True

                target = args[0]
                instance = self.provider.instance_manager.get_instance(target)
                if instance is None:
                    logger.log("CLI", f"Unable to get Instance with name '{instance}'")
                    return True
                
                if self.provider.run_parameters is None or self.provider.run_parameters.preserve is None:
                    logger.log("CLI", f"File preservation is not enabled in this testbed run.")
                    return True
                
                instance.add_preserve_file(args[1])
                logger.log("CLI", f"File '{args[1]}' was as added to preserve list of Instance '{target}'")
                return True

            case "list" | "ls":
                if self.provider.instance_manager is None:
                    logger.log("CLI", f"No Instances available to list.")
                    return True
                
                def info_instance_callback(instance):
                    line = f"- Instance '{instance.name}' ({instance.uuid}) | {instance.get_state().name}"
                    if len(instance.interfaces) != 0:
                        line += f" | Interfaces: {', '.join(list(map(lambda x: f'{x.bridge.name} -> {x.interface_on_instance}', instance.interfaces)))}"
                    if instance.mgmt_ip_addr is not None:
                        line += f" | MGMT IP: {instance.mgmt_ip_addr}"
                    logger.log("CLI", line)

                self.provider.instance_manager.do_for_all_instances_sequential(info_instance_callback)
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

            case "restart" | "r":
                self.continue_mode.update(ContinueMode.RESTART)
                if self.continue_event is None:
                    logger.log("CLI", "Unable to exit testbed, continue_event object missing.")
                    return True
                else:
                    logger.log("CLI", f"Restarting testbed. Interaction will be disabled.")
                    self.continue_event.set()
                    return True

            case "help" | "h":
                logger.opt(ansi=True).log("CLI", "--------- Proto²Testbed Interactive Mode Help ---------")
                logger.opt(ansi=True).log("CLI", "  <u>c</u>ontinue (INIT|EXPERIMENT) -> Continue testbed (to next pause step)", color=True)
                logger.opt(ansi=True).log("CLI", "  <u>a</u>ttach \<Instance>          -> Attach to TTY of an Instance", color=True)
                logger.opt(ansi=True).log("CLI", "  <u>c</u>o<u>p</u>y (\<Instance>:)\<Path> (\<Instance>:)\<Path> -> Copy files from/to instance", color=True)
                logger.opt(ansi=True).log("CLI", "  <u>l</u>i<u>s</u>t                       -> List all Instances in testbed", color=True)
                logger.opt(ansi=True).log("CLI", "  <u>p</u>reserve \<Instance>:\<Path> -> Mark file or directory for preservation", color=True)
                logger.opt(ansi=True).log("CLI", "  <u>e</u>xit                       -> Terminate testbed", color=True)
                logger.opt(ansi=True).log("CLI", "  <u>r</u>estart                    -> Request a full testbed restart", color=True)
                logger.opt(ansi=True).log("CLI", "  <u>h</u>elp                       -> Show this help", color=True)
                logger.opt(ansi=True).log("CLI", "  <u>r</u>estore                    -> Restore setup checkpoint", color=True)
                logger.opt(ansi=True).log("CLI", "  <u>s</u>et \<Parameter> \<Value>    -> Change testbed parameters", color=True)
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
                if self.kill_input.is_set():
                    logger.log("CLI", "Input was interrupted by external shutdown request.")
                    self.continue_event.set()
                    return

                if not self.enable_interaction.is_set():
                    self.enable_interaction.wait()
                    clear_stdin()
                    continue
            except EOFError:
                continue
            
            parts = cli_input.strip().split(" ", maxsplit=1)
            if len(parts) != 2:
                command, args = parts[0], None
            else:
                command, args = parts
                args = args.split(" ")

            command = command.lower()

            if command == "":
                continue
            
            status = False
            try:
                status = self.handle_command(command, args)
            except Exception as ex:
                status = False
                logger.opt(exception=ex).error("Error running command")
            
            if not status:
                logger.log("CLI", f"Unknown command '{command}' or error running it, use 'help' to show available commands.")

    def set_full_result_wrapper(self, full_result_wrapper):
        self.full_result_wrapper = full_result_wrapper


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
        if self.provider.instance_manager is None:
            return

        self.continue_event = event
        self.continue_mode = continue_mode
        self.toggle_interaction(True)

    def stop_cli(self):
        if self.provider.instance_manager is None:
            return
        
        self.continue_event = None
        self.toggle_interaction(False)

    def start(self):
        if self.provider.instance_manager is None:
            return
        
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()

    def unblock_input(self):
        self.kill_input.set()

        if self.enable_interaction.is_set():
            self.toggle_interaction(False)
        
        self.continue_event.set()

    def stop(self):
        pass

    def get_name(self) -> str:
        return "CLI Handler"

    def dismantle(self, force: bool = False) -> None:
        self.stop()
