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
import threading

from typing import Optional, List, Dict
from pathlib import Path
from dataclasses import dataclass
from queue import Queue

from management_client import ManagementClient
from applications.base_application import BaseApplication
from common.application_configs import ApplicationConfig, AppStartStatus
from application_controller import ApplicationController
from common.instance_manager_message import InstanceMessageType
from common.application_loader import ApplicationLoader
from global_state import GlobalState


@dataclass
class ApplicationEvent:
    status: AppStartStatus
    app: ApplicationController


class ApplicationManager:
    def __init__(self, main, manager: ManagementClient, instance_name: str) -> None:
        self.main = main
        self.manager = manager
        self.instance_name = instance_name
        self.loader = ApplicationLoader(
            Path(GlobalState.start_exec_path), 
            Path(GlobalState.testbed_package_path),
            ["set_and_validate_config", "start"])
        self.app_exec_init: Optional[List[ApplicationController]] = None
        self.app_exec_deferred: Optional[Dict[str, ApplicationController]] = None

        self.app_collect_list: Optional[List[ApplicationController]] = None
        self.running: List[ApplicationController] = []
        self.event_queue = Queue()

        self.colletor_thread = threading.Thread(target=self._run_event_collector, daemon=True)

        try:
            self.loader.read_packaged_apps()
        except Exception as ex:
            print(f"Unable to load packaged applications: {ex}", file=sys.stderr, flush=True)
            self.main.message_to_controller(InstanceMessageType.FAILED, 
                                            f"Failure during loading of packaged apps: {ex}")

    def __del__(self) -> None:
        self._destory_apps()

    def _run_event_collector(self) -> None:
        failed = 0
        collected = 0
        while self.app_collect_list:
            event: ApplicationEvent = self.event_queue.get()

            if event.status == AppStartStatus.DAEMON:
                self.app_collect_list.remove(event.app)
                collected += 1
                continue

            self.main.single_app_status_changed(event.app.config.name, event.status)

            if event.status == AppStartStatus.FINISH:
                self.app_collect_list.remove(event.app)
                event.app.join()
                collected += 1
                if event.app.error_occurred():
                    failed += 1

        if collected != (len(self.app_exec_deferred) + len(self.app_exec_init)):
            print(f"Not all Applications were completed yielding finished event!")
            self.main.message_to_controller(InstanceMessageType.MSG_ERROR,
                                            f"Not all Applications were completed yielding 'finished' event!")
            for app in self.running:
                if app.config.runtime is None:
                    continue
                
                app.join()
                failed += 1

        self.main.all_apps_status_changed(failed)


    def _destory_apps(self) -> None:
        for app in self.running:
            app.join()

        if self.app_exec_init is not None:
            for app_controller in self.app_exec_init:
                del app_controller

        if self.app_exec_deferred is not None:
            for app_controller in self.app_exec_deferred.values():
                del app_controller

    def install_apps(self, apps: Optional[List[ApplicationConfig]]) -> bool:
        self.app_exec_init = []
        self.app_exec_deferred = {}
        self.app_collect_list = []

        if apps is None:
            return True
        
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
            
            app_controller = ApplicationController(app_instance, config, self.manager, self.instance_name, self)
            self.app_collect_list.append(app_controller)

            if config.depends is None or len(config.depends) == 0:
                self.app_exec_init.append(app_controller)
            else:
                app_controller.start_defered = True
                self.app_exec_deferred[config.name] = app_controller
        
        self.main.message_to_controller(InstanceMessageType.MSG_DEBUG, 
                                                        f"Apps loaded: {self.loader.loaded_apps_size()}, Scheduled to execute instant: {len(self.app_exec_init)}, with dependency: {len(self.app_exec_deferred)}")
        self.main.message_to_controller(InstanceMessageType.APPS_INSTALLED)
        self.colletor_thread.start()
        return True

    def run_initial_apps(self, t0: float) -> bool:
        if self.app_exec_init is None:
            print(f"No application are installed, nothing to execute.", file=sys.stderr, flush=True)
            self.main.message_to_controller(InstanceMessageType.APPS_DONE)
            return True

        print(f"Starting execution of Applications", file=sys.stderr, flush=True)

        for controller in self.app_exec_init:
            controller.update_t0(t0)
            controller.start()
            self.running.append(controller)

        return True
        
    def run_deferred_app(self, name: str, status: AppStartStatus) -> bool:
        if name not in self.app_exec_deferred.keys():
            return False
        
        for key, value in self.app_exec_deferred.items():
            if key != name:
                continue

            value.start()
            self.main.message_to_controller(InstanceMessageType.MSG_DEBUG, 
                                            f"Deferred Application started: {value.config.name}")
            self.running.append(value)

        return True

    def report_app_status(self, app: ApplicationController, status: AppStartStatus) -> None:
        self.event_queue.put(ApplicationEvent(status=status, app=app))
