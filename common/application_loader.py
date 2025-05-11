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

import importlib.util
import inspect
import os

from typing import Tuple, Optional, Dict, Any, List
from pathlib import Path

from applications.base_application import BaseApplication


class ApplicationLoader:
    __COMPATIBLE_API_VERSION = "1.0"
    __PACKAGED_APPS = "applications/"

    def __init__(self, app_base: Path, 
                 testbed_package_base: Path, 
                 required_methods: List[str]) -> None:
        self.app_base = app_base
        self.testbed_package_base = testbed_package_base
        self.required_methods = required_methods
        self.app_map: Dict[str, Any] = {}

    def _check_valid_app(self, cls) -> Tuple[bool, Optional[str]]:
        if not issubclass(cls, BaseApplication) or cls.__name__ == "BaseApplication":
            return False, None
        
        if not hasattr(cls, "API_VERSION"):
            return False, "API_VERSION missing"
        
        if not hasattr(cls, "NAME"):
            return False, "NAME missing"
        
        if cls.API_VERSION != ApplicationLoader.__COMPATIBLE_API_VERSION:
            return False, f"Incompatible API version: {cls.API_VERSION}, but {ApplicationLoader.__COMPATIBLE_API_VERSION} required"
        
        if cls.NAME == BaseApplication.NAME:
            return False, None
        
        for method in self.required_methods:
            if not hasattr(cls, method) or not callable(getattr(cls, method)):
                return False, f"At least method '{method}' is missing"
            
        return True, None
    
    def _load_single_app(self, module_name: str, path: Path, 
                         loaded_by_package: bool = False) -> Tuple[bool, Optional[str]]:
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as ex:
            return False, f"Python file '{path}' not loadable: {ex}"

        added = 0
        last_message = None
        for _, obj in inspect.getmembers(module, inspect.isclass):
            status, message = self._check_valid_app(obj)
            if not status:
                if message is not None:
                    last_message = message
                continue

            class_name = obj.NAME
            if loaded_by_package:
                self.app_map[module_name] = obj
                return True, None

            self.app_map[class_name] = obj
            added += 1
        
        if added != 0:
            return True, None
        else:
            return False, last_message


    def read_packaged_apps(self) -> None:
        for filename in os.listdir(self.app_base / Path(ApplicationLoader.__PACKAGED_APPS)):
            filepath = Path(os.path.join(self.app_base, ApplicationLoader.__PACKAGED_APPS, filename)).absolute()

            if not os.path.isfile(str(filepath)) or not filename.endswith(".py"):
                continue

            module = filename[:-3] # Skip "".py"
            self._load_single_app(module, filepath)

    def load_app(self, application: str, reload: bool = False, 
                 absolute_path: bool = False) -> Tuple[Optional[BaseApplication], str]:
        if application in self.app_map.keys():
            return self.app_map[application], "Loaded packaged application"
        
        if reload is False:
            return None, "Application not packaged and reload is disabled"
    
        app_file = application
        if not app_file.endswith(".py"):
            app_file += ".py"

        if absolute_path:
            module_path = Path(app_file)
        else:
            module_path = self.testbed_package_base / Path(app_file)

        status, message = self._load_single_app(application, module_path, True)

        if not status:
            if message is None:
                message = "Not found"
            return None, f"Unable to load app from {module_path}: {message}"
        
        app_cls = self.app_map.get(application, None)
        if absolute_path:
            return app_cls, "Loaded from absolute path" if app_cls is not None else "Unable to load requested app"
        else:
            return app_cls, "Loaded from testbed package" if app_cls is not None else "Unable to load requested app"
    
    def loaded_apps_size(self) -> int:
        return len(self.app_map)
