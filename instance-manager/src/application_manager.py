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

from typing import Optional, List
from pathlib import Path
from threading import Barrier

from management_client import ManagementClient
from applications.base_application import BaseApplication
from common.application_configs import ApplicationConfig
from application_controller import ApplicationController
from common.instance_manager_message import InstanceMessageType
from common.application_loader import ApplicationLoader
from global_state import GlobalState


class ApplicationManager:
    def __init__(self, main, manager: ManagementClient, instance_name: str) -> None:
        self.main = main
        self.manager = manager
        self.instance_name = instance_name
        self.loader = ApplicationLoader(
            Path(GlobalState.start_exec_path), 
            Path(GlobalState.testbed_package_path),
            ["set_and_validate_config", "start"])
        self.app_exec: List[ApplicationController] = None
        self.barrier = None

        try:
            self.loader.read_packaged_apps()
        except Exception as ex:
            print(f"Unable to load packaged applications: {ex}", file=sys.stderr, flush=True)
            self.main.message_to_controller(InstanceMessageType.FAILED, 
                                            f"Failure during loading of packaged apps: {ex}")

    def __del__(self) -> None:
        self._destory_apps()

    def _destory_apps(self):
        if self.app_exec is not None:
            for app_controller in self.app_exec:
                del app_controller

    def install_apps(self, apps: Optional[List[ApplicationConfig]]) -> bool:
        self.app_exec = []

        if apps is None:
            return True
        
        self.barrier = Barrier(len(apps) + 1)
        
        for config in apps:
            app_cls, message = self.loader.load_app(config.application, True, config.load_from_instance)

            if app_cls is None:
                if message is not None:
                    print(f"Unable to install app '{config.name}@{config.application}': {message}", file=sys.stderr, flush=True)
                    self.main.message_to_controller(InstanceMessageType.FAILED, 
                                                    f"Unable to install app '{config.name}@{config.application}': {message}")
                else:
                    print(f"Unable to install app '{config.name}@{config.application}': Not found.", file=sys.stderr, flush=True)
                    self.main.message_to_controller(InstanceMessageType.FAILED, 
                                                    f"Unable to install app '{config.name}@{config.application}': Not found.")
                return False
                
            print(f"Loaded App '{config.application}': {message}", file=sys.stderr, flush=True)
            self.main.message_to_controller(InstanceMessageType.MSG_DEBUG, 
                                            f"Loaded App '{config.application}': {message}")

            try:
                app_instance: BaseApplication = app_cls()
                status, message = app_instance.set_and_validate_config(config.settings)

                if not status:
                    if message is not None:
                        self.main.message_to_controller(InstanceMessageType.FAILED, 
                                                        f"Unable to validate config for app '{config.name}@{config.application}': {message}")
                    else:
                        self.main.message_to_controller(InstanceMessageType.FAILED, 
                                                        f"Unable to validate config for app '{config.name}@{config.application}': Unspecified error.")
                elif message is not None:
                        self.main.message_to_controller(InstanceMessageType.MSG_INFO, 
                                                        f"Message during config validation for app '{config.name}@{config.application}': {message}")

                
                if not status:
                    print(f"Unable to validate config for app '{config.name}@{config.application}': {message}", file=sys.stdout, flush=True)
                    self._destory_apps()
                    return False
            except Exception as ex:
                self.main.message_to_controller(InstanceMessageType.FAILED, 
                                                        f"Unable to validate config for app '{config.name}@{config.application}': Unhandeled error: {ex}.")
                print(f"Unhandeled error while validate config for app '{config.name}@{config.application}': {ex}", file=sys.stdout, flush=True)
                self._destory_apps()
                return False
            
            app_controller = ApplicationController(app_instance, config, 
                                                   self.manager, self.barrier, 
                                                   self.instance_name)
            self.app_exec.append(app_controller)
        
        self.main.message_to_controller(InstanceMessageType.MSG_DEBUG, 
                                                        f"Apps loaded: {self.loader.loaded_apps_size()}, Scheduled to execute: {len(self.app_exec)}")
        self.main.message_to_controller(InstanceMessageType.APPS_INSTALLED)
        return True
        

    def run_apps(self) -> bool:
        if self.app_exec is None:
            print(f"No application are installed, nothing to execute.", file=sys.stderr, flush=True)
            self.main.message_to_controller(InstanceMessageType.APPS_DONE)
            return True

        print(f"Starting execution of Applications", file=sys.stderr, flush=True)

        threads = []
        for controller in self.app_exec:
            controller.start()
            threads.append(controller)

        self.barrier.wait()

        failed = 0
        for t in threads:
            t.join()
            if t.error_occurred():
                failed += 1

        if failed != 0:
            print(f"Execution of Applications finished, {failed} failed.", file=sys.stderr, flush=True)
            self.main.message_to_controller(InstanceMessageType.APPS_FAILED, 
                                        f"{failed} Applications(s) failed.")
            return True
        else:
            print(f"Execution of Applications successfully completed.", file=sys.stderr, flush=True)
            self.main.message_to_controller(InstanceMessageType.APPS_DONE)
            return True
