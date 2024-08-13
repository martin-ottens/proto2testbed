import os
import time
import signal
import psutil
import signal
import stat

from typing import Optional, Any, Tuple
from pathlib import Path
from loguru import logger
from multiprocessing import Process, Manager

from utils.interfaces import Dismantable
from utils.system_commands import invoke_subprocess
from utils.settings import *

class IntegrationHelper(Dismantable):
    def __init__(self, settings: Integration, base_path: Path) -> None:
        self.settings: Integration = settings
        self.base_path = base_path
        self.dismantle_action = None
        self.dismantle_context: Any = None
        self.manager = Manager()
        self.shared_state = self.manager.dict()
        self.shared_state["error_flag"] = False
        self.shared_state["error_string"] = None

        self.process = None

    def __del__(self) -> None:
        self.dismantle()

    def __kill_process_with_child(self, process: Process):
        try:
            parent = psutil.Process(process.ident)
            for child in parent.children(recursive=True):
                try: child.send_signal(signal.SIGTERM)
                except Exception as ex:
                    logger.opt(exception=ex).critical("Integration: Unable to kill child.")
                    continue
        except Exception as ex:
            logger.opt(exception=ex).critical("Integration: Unable to get child processes.")

        process.terminate()

    def __get_and_check_script(self, rel_path_str: str, name: str) -> Optional[Path]:
        script_file = self.base_path / Path(rel_path_str)
        if not script_file.exists() or not script_file.is_relative_to(self.base_path):
            logger.critical(f"Integration: Unable to get {name} script file '{script_file}'!")
            return None

        if not (script_file.stat() & (stat.S_IXUSR & stat.S_IXGRP & stat.S_IXOTH)):
            logger.critical(f"Integration: {name.capitalize()} script file '{script_file}' has invalid permissions!")
            return None

        return script_file


    def __run_subprocess(self, script_path):
        """
        Important: This method will be forked away from the main process!
        """

        for k, v in self.settings.environment.items():
            os.environ[k] = v
        
        try:
            proc = invoke_subprocess(["/bin/bash", script_path], capture_output=True, shell=False)
            if proc is not None (proc.returncode != 0 or proc.stderr != ""):
                self.shared_state["error_flag"] = True
                if proc.stderr != "":
                    self.shared_state["error_string"] = f"Failed with exit code {proc.returncode}\nSTDOUT: {proc.stdout}\nSTDERR; {proc.stderr}"
                else:
                    self.shared_state["error_string"] = f"Failed with exit code {proc.returncode}\nSTDOUT: {proc.stdout}"
        except Exception as ex:
            self.shared_state["error_flag"] = True
            self.shared_state["error_string"] = f"Error during execution: {ex}"

    def dismantle_await(self) -> None:
        pass

    def start_await(self, settings: AwaitIntegrationSettings) -> bool:
        start_script = self.__get_and_check_script(settings.start_script, "start")

        if start_script is None:
            logger.critical(f"Integration: Unable to find start script file!")
            return False

        self.process = Process(target=self.__run_subprocess, args=(start_script, ))
        start_time = time.time()

        time.sleep(0.1)

        if not self.process.is_alive() and self.shared_state["error_flag"]:
            logger.critical(f"Integration: Script exited with error: {self.shared_state['error_string'] if self.shared_state['error_string'] is not None else ''}")
            return False
        
        self.dismantle_action = self.dismantle_await
        self.dismantle_context = (start_time, settings.wait_for_exit, )
        return True

    def start_startstop(self, settings: StartStopIntegrationSettings) -> bool:
        start_script = self.__get_and_check_script(settings.start_script, "start")
        stop_script = self.__get_and_check_script(settings.stop_script, "stop")

        if start_script is None or stop_script is None:
            logger.critical(f"Integration: Unable to find start and/or stop script file!")
            return False

        process = Process(target=self.__run_subprocess, args=(start_script, ))

        status = True
        process.start()
        process.join(settings.wait_for_exit)
        if process.is_alive():
            logger.critical(f"Integration: Start script runs longer than {settings.wait_for_exit}, terminating ...")
            self.__kill_process_with_child(process)
            status = False
        
        if self.shared_state["error_flag"]:
            logger.critical(f"Integration: Unable to run start script: {self.shared_state['error_string'] if self.shared_state['error_string'] is not None else ''}")
            status = False

        self.dismantle_action = self.dismantle_startstop
        self.dismantle_context = (stop_script, settings.wait_for_exit, )
        return status

    def handle_stage_start(self, stage: InvokeIntegrationAfter) -> Optional[bool]:
        if stage != self.settings.invoke_after:
            return None
        
        logger.info(f"Integration: Starting {self.settings.mode} as stage {stage}.")
        
        match self.settings.mode:
            case IntegrationMode.NONE:
                return None
            case IntegrationMode.AWAIT:
                if not isinstance(self.settings.settings, AwaitIntegrationSettings):
                    raise Exception("Invalid integration setting supplied!")
                return self.start_await(self.settings.settings)
            case IntegrationMode.STARTSTOP:
                if not isinstance(self.settings.settings, StartStopIntegrationSettings):
                    raise Exception("Invalid integration setting supplied!")
                return self.start_startstop(self.settings.settings)
            case _:
                raise Exception("Invalid integration mode supplied!")
        
    def dismantle_await(self, context: Optional[Tuple[float, int]]) -> None:
        if context is None or self.process is None:
            logger.critical("Conditions to dismantle Await Integration not fullfilled!")
            return
        
        if context[1] != -1:
            to_wait = context[1] - (time.time() - context[0])
            if to_wait > 0:
                logger.info(f"Integration: Waiting {to_wait} seconds for script to complete.")
                self.process.join(to_wait)
        
        if self.process.is_alive():
            if context[1] != -1:
                logger.critical(f"Integration: Script runs did not finished in {context[2]} seconds, terminating ...")
            self.__kill_process_with_child(self.process)

        if self.shared_state["error_flag"]:
            logger.critical(f"Integration: Unable to run stop script: {self.shared_state['error_string'] if self.shared_state['error_string'] is not None else ''}")

    def dismantle_startstop(self, context: Optional[Tuple[str, int]]) -> None:
        if context is None or self.process is not None:
            logger.critical("Conditions to dismantle StartStop Integration not fullfilled!")
            return
        
        # New process -> Reset error states
        self.shared_state["error_flag"] = False
        self.shared_state["error_string"] = None
        
        process = Process(target=self.__run_subprocess, args=(context[0], ))

        process.start()
        process.join(context[1])
        if process.is_alive():
            if context[1] != -1:
                logger.critical(f"Integration: Stop script runs longer than {context[1]}, terminating ...")
            self.__kill_process_with_child(process)
        
        if self.shared_state["error_flag"]:
            logger.critical(f"Integration: Unable to run stop script: {self.shared_state['error_string'] if self.shared_state['error_string'] is not None else ''}")

    def dismantle(self) -> None:
        if self.dismantle_action is not None:
            self.dismantle_action(self.dismantle_context)
            logger.info("Integration: Integration was stopped.")

    def get_name(self) -> str:
        return "IntegrationHelper"
