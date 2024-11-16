import os
import importlib.util
import inspect
import sys

from typing import Optional, List, Dict, Any
from pathlib import Path
from threading import Barrier

from management_client import ManagementClient
from base_application import BaseApplication
from common.application_configs import ApplicationConfig
from application_controller import ApplicationController
from common.instance_manager_message import InstanceMessageType
from global_state import GlobalState


class ApplicationManager():
    __COMPATIBLE_API_VERSION = "1.0"
    __PACKAGED_APPS = "applications/"

    def __init__(self, main, manager: ManagementClient, instance_name: str) -> None:
        self.main = main
        self.manager = manager
        self.instance_name = instance_name
        self.app_base = Path(GlobalState.start_exec_path)
        self.testbed_package_base = Path(GlobalState.testbed_package_path)
        self.app_map: Dict[str, Any] = {}
        self.app_exec: List[ApplicationController] = None
        self.barrier = None

        self._read_packaged_apps()

    def __del__(self) -> None:
        self._destory_apps()

    def _destory_apps(self):
        if self.app_exec is not None:
            for app_controller in self.app_exec:
                del app_controller

    def _check_valid_app(self, cls, loaded_file) -> bool:
        if not issubclass(cls, BaseApplication) or cls.__name__ == "BaseApplication":
            return False
        
        if not hasattr(cls, "API_VERSION"):
            print(f"AppLoader: File '{loaded_file}' has no API_VERSION", file=sys.stdout, flush=True)
            return False
        
        if not hasattr(cls, "NAME"):
            print(f"AppLoader: File '{loaded_file}' has no NAME", file=sys.stdout, flush=True)
            return False
        
        if cls.API_VERSION != ApplicationManager.__COMPATIBLE_API_VERSION:
            print(f"AppLoader: File '{loaded_file}' has API_VERSION {cls.API_VERSION}, but {ApplicationManager.__COMPATIBLE_API_VERSION} required.", file=sys.stdout, flush=True)
            return False
        
        if cls.NAME == BaseApplication.NAME:
            return False
        
        for method in ["set_and_validate_config", "start"]:
            if not hasattr(cls, method) or not callable(getattr(cls, method)):
                print(f"AppLoader: File '{loaded_file}' is missing method '{method}'", file=sys.stdout, flush=True)
                return False
            
        return True
    
    def _load_single_app(self, module_name: str, path: Path, 
                         loaded_by_package: bool = False) -> bool:
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as ex:
            print(ex)
            return False

        added = 0
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if not self._check_valid_app(obj, path):
                continue

            class_name = obj.NAME
            print(f"AppLoader: Loaded '{class_name}' from file '{path}'", file=sys.stdout, flush=True)
            if loaded_by_package:
                self.app_map[module_name] = obj
                return True

            self.app_map[class_name] = obj
            added += 1
        
        return added != 0


    def _read_packaged_apps(self) -> None:
        for filename in os.listdir(self.app_base / Path(ApplicationManager.__PACKAGED_APPS)):
            filepath = Path(os.path.join(self.app_base, ApplicationManager.__PACKAGED_APPS, filename)).absolute()

            if not os.path.isfile(str(filepath)) or not filename.endswith(".py"):
                continue

            module = filename[:-3] # Skip "".py"
            self._load_single_app(module, filepath)


    def install_apps(self, apps: Optional[List[ApplicationConfig]]) -> bool:
        self.app_exec = []

        if apps is None:
            return True
        
        self.barrier = Barrier(len(apps) + 1)
        
        for config in apps:
            if config.application not in self.app_map.keys():
                # Try to load from testbed package
                app_file = config.application
                if not app_file.endswith(".py"):
                    app_file += ".py"

                module_path = self.testbed_package_base / Path(app_file)

                if not self._load_single_app(config.application, module_path, True):
                    self.main.message_to_controller(InstanceMessageType.FAILED, 
                                                    f"Unable to install app '{config.name}@{config.application}': Not found.")
                    return False
                self.main.message_to_controller(InstanceMessageType.MSG_DEBUG, 
                                                f"Loaded App '{config.application}' from testbed package.")


            app_instance: BaseApplication = self.app_map[config.application]()

            try:
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
                                                        f"Apps loaded: {len(self.app_map)}, Scheduled to execute: {len(self.app_exec)}")
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
            if t.error_occured():
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
