#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2024 Martin Ottens
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

import threading
import time
import importlib.util
import inspect
import os

from loguru import logger
from typing import List, Optional
from dataclasses import dataclass
from pathlib import Path

from utils.interfaces import Dismantable
from utils.settings import *
from base_integration import BaseIntegration, IntegrationStatusContainer


@dataclass
class IntegrationExecutionWrapper:
    obj: Integration
    impl: BaseIntegration
    status: IntegrationStatusContainer
    thread: threading.Thread = None
    started: bool = False
    started_at: float = 0
    is_shutdown: bool = False

class IntegrationLoader():
    __COMPATIBLE_API_VERSION = "1.0"
    __PACKAGED_INTEGRATIONS = "integrations/"

    def __init__(self, testbed_package_base: str, app_base: str) -> None:
        self.testbed_package_base = Path(testbed_package_base)
        self.app_base = Path(app_base)
        self.integration_map: Dict[str, BaseIntegration] = {}

    def _check_valid_integration(self, cls, loaded_file) -> bool:
        if not issubclass(cls, BaseIntegration) or cls.__name__ == "BaseIntegration":
            return False
        
        if not hasattr(cls, "API_VERSION"):
            logger.trace(f"IntegrationLoader: Integration in '{loaded_file}' has no API_VERSION")
            return False
        
        if not hasattr(cls, "NAME"):
            logger.trace(f"IntegrationLoader: Integration in '{loaded_file}' has no NAME")
            return False
        
        if cls.API_VERSION != IntegrationLoader.__COMPATIBLE_API_VERSION:
            logger.trace(f"IntegrationLoader: Integration in '{loaded_file}' has API_VERSION {cls.API_VERSION}, but {IntegrationLoader.__COMPATIBLE_API_VERSION} required.")
            return False
        
        if cls.NAME == BaseIntegration.NAME:
            logger.warning(f"IntegrationLoader: Integration in '{loaded_file}' has no own NAME!")
            return False
        
        for method in ["set_and_validate_config", "is_integration_blocking", "get_expected_timeout", "start", "stop"]:
            if not hasattr(cls, method) or not callable(getattr(cls, method)):
                logger.trace(f"IntegrationLoader: Integration in '{loaded_file}' is missing method '{method}'")
                return False
            
        return True

    def _load_single_integration(self, module_name: str, path: Path, 
                                 loaded_by_package: bool = False) -> bool:
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as ex:
            logger.opt(exception=ex).debug(f"Error while loading integration from '{path}'")
            return False
        
        added = 0
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if not self._check_valid_integration(obj, path):
                continue

            class_name = obj.NAME
            logger.debug(f"IntegrationLoader: Loaded '{class_name}' from file '{path}'")
            if loaded_by_package:
                self.integration_map[module_name] = obj
                return True

            self.integration_map[class_name] = obj
            added += 1

        return added != 0

    def init_packaged_integrations(self) -> None:
        for filename in os.listdir(self.app_base / Path(IntegrationLoader.__PACKAGED_INTEGRATIONS)):
            filepath = Path(os.path.join(self.app_base, IntegrationLoader.__PACKAGED_INTEGRATIONS, filename)).absolute()

            if not os.path.isfile(str(filepath)) or not filename.endswith(".py"):
                continue
                
            module = filename[:-3] # Skip ".py"
            self._load_single_integration(module, filepath)

    def get_packaged_or_try_load(self, name: str) -> Optional[BaseIntegration]:
        integration = self.integration_map.get(name, None)
        if integration is not None:
            return integration

        file_name = name
        if not name.endswith(".py"):
            file_name += ".py"

        module_path = self.testbed_package_base / Path(file_name)
        if not self._load_single_integration(name, module_path, True):
            logger.critical(f"IntegrationLoader: Unable to load Integration '{name}' from testbed package.")
            return None
        
        return self.integration_map.get(name)


class IntegrationHelper(Dismantable):
    def __init__(self, testbed_package_base: str, app_base: str) -> None:
        self.loader = IntegrationLoader(testbed_package_base, app_base)
        self.integrations = None

        self.mapped_integrations = {
            InvokeIntegrationAfter.INIT: [],
            InvokeIntegrationAfter.NETWORK: [],
            InvokeIntegrationAfter.STARTUP: []
        }

    def apply_configured_integrations(self, integrations: List[Integration]):
        self.loader.init_packaged_integrations()
        self.integrations = integrations

        for integration in integrations:
            integration_obj = self.loader.get_packaged_or_try_load(integration.type)
            if integration_obj is None:
                raise Exception(f"Integration '{integration.name}' of type '{integration.type}' could not be loaded.")
            
            integration_status = IntegrationStatusContainer()
            integration_impl: BaseIntegration = integration_obj(integration.name,
                                                                integration_status,
                                                                integration.environment)
            
            status, message = integration_impl.set_and_validate_config(integration.settings)
            if not status:
                if message is not None:
                    raise Exception(f"Unable to validate config for Integration '{integration.name}@{integration.type}': {message}")
                else:
                    raise Exception(f"Unable to validate config for Integration '{integration.name}@{integration.type}': Unspecified error.")
            elif message is not None:
                logger.debug(f"Message during successful config validation for Integration '{integration.name}@{integration.type}': {message}")
            
            self.mapped_integrations[integration.invoke_after].append(IntegrationExecutionWrapper(
                        integration, 
                        integration_impl, 
                        integration_status))
        
        scheduled = ", ".join(map(lambda x: f"Stage {x[0].name}: {len(x[1])}", self.mapped_integrations.items()))
        logger.debug(f"Integrations loaded: {len(self.loader.integration_map)}; Scheduled for exceution: {scheduled}")
            
    def __del__(self) -> None:
        self.force_shutdown()

    def _get_all_integration_wrappers(self) -> List[IntegrationExecutionWrapper]:
        result: List[IntegrationExecutionWrapper] = []
        for _, mapping in self.mapped_integrations.items():
            result.extend(mapping)

        return result

    def _fire_integration(self, exec: IntegrationExecutionWrapper, barrier: threading.Barrier):
        def integration_thread(exec: IntegrationExecutionWrapper, barrier: threading.Barrier):
            barrier.wait()
            exec.started_at = time.time()

            logger.trace(f"Calling start of integration '{exec.obj.name}'")
            try:
                exec.impl.start()

                if exec.status.get_error() is not None:
                    logger.error(f"Integration: Start of integration '{exec.obj.name}' failed: {exec.status.get_error()}")
            except Exception as ex:
                logger.opt(exception=ex).error(f"Integration: Start of '{exec.obj.name}' failed")
                exec.status.set_error(ex)

            exec.status.set_finished()
            logger.trace(f"Integration start thread '{exec.obj.name}' terminates now.")
        
        exec.started = True
        exec.thread = threading.Thread(target=integration_thread, args=(exec, barrier, ), daemon=True)
        logger.info(f"Integration: Invoking start of integration '{exec.obj.name}'")
        exec.thread.start()

    def _stop_integration(self, exec: IntegrationExecutionWrapper):
        def integration_thread(exec: IntegrationExecutionWrapper):
            exec.started_at = time.time()

            logger.trace(f"Calling stop of integration '{exec.obj.name}'")
            try:
                exec.impl.stop()

                if exec.status.get_error() is not None:
                    logger.error(f"Integration: Stop of integration '{exec.obj.name}' failed: {exec.status.get_error()}")
            except Exception as ex:
                logger.opt(exception=ex).error(f"Integration: Stop of '{exec.obj.name}' failed")
                exec.status.set_error(ex)
        
            exec.status.set_finished()
            logger.trace(f"Integration stop thread '{exec.obj.name}' terminates now.")
        
        exec.thread = threading.Thread(target=integration_thread, args=(exec, ), daemon=True)
        logger.info(f"Integration: Invoking stop of integration '{exec.obj.name}'")
        exec.thread.start()
    
    # Returns:
    # - None = No integration fired
    # - True = All integrations okay
    # - False = At least one integration failed at invoke
    def handle_stage_start(self, stage: InvokeIntegrationAfter) -> Optional[bool]:
        # 0. Check always if there are previous failed integrations
        if self.has_error():
            logger.critical(f"Integration: Integration failure occured before stage {str(stage).upper()}")
            return False
        
        logger.debug(f"Integration: Checking & invoking integrations at stage {str(stage).upper()}")

        # 1. Find integrations to be invoked at this stage
        fire_integrations: List[IntegrationExecutionWrapper] = self.mapped_integrations[stage]

        if fire_integrations is None or len(fire_integrations) == 0:
            return None
        
        if TestbedSettingsWrapper.cli_paramaters.skip_integration:
            for integration in fire_integrations:
                logger.warning(f"Integration: Start of '{integration.obj.name}' integration at stage {str(stage).upper()} skipped.")
            return None

        # 2. Find blocking/non blocking integrations, find largest wait_after_invoke value
        sync_integrations: List[IntegrationExecutionWrapper] = []
        async_integrations: List[IntegrationExecutionWrapper] = []
        wait_after_invoked: int = 0
        for integration in fire_integrations:
            if integration.obj.wait_after_invoke > wait_after_invoked:
                wait_after_invoked = integration.obj.wait_after_invoke

            if integration.impl.is_integration_blocking():
                sync_integrations.append(integration)
            else:
                async_integrations.append(integration)
        
        # 3. Fire all blocking integrations at parallel
        if len(sync_integrations) != 0:
            sync_barrier = threading.Barrier(len(sync_integrations) + 1)
            expected_max_timeout = 0
            for sync_integration in sync_integrations:
                if sync_integration.impl.get_expected_timeout(at_shutdown=False) > expected_max_timeout:
                    expected_max_timeout = sync_integration.impl.get_expected_timeout(at_shutdown=False)
                self._fire_integration(sync_integration, sync_barrier)
            
            sync_barrier.wait() # No interrupt handling -> Wait time is short!
            wait_until = time.time() + expected_max_timeout + 1
            logger.debug(f"Integration: Waiting {expected_max_timeout:.2f} seconds for start phase of blocking integrations to finish!")
            status = True
            for sync_integration in sync_integrations:
                logger.trace(f"Waiting for blocking start of integration '{sync_integration.obj.name}'")
                try:
                    sync_integration.thread.join(wait_until - time.time())
                    if sync_integration.thread.is_alive():
                        logger.critical(f"Integration: Timeout joining '{sync_integration.obj.name}' start thread.")
                        status = False
                        continue

                    if sync_integration.status.get_error() is not None:
                        logger.critical(f"Integration: Integration '{sync_integration.obj.name}' reported failure")
                        sync_integration.status.reset_error()
                        status = False

                except InterruptedError:
                    logger.critical("Integration: Waiting for blocking integrations was interrupted!")
                    return False
                
            if not status:
                logger.critical("Integration: At least one integration start phase in blocking mode failed")
                return False

        # 4. Fire all non-blocking integrations
        if len(async_integrations) != 0:
            async_barrier = threading.Barrier(len(async_integrations) + 1)

            for async_integration in async_integrations:
                self._fire_integration(async_integration, async_barrier)

            async_barrier.wait() # No interrupt handling -> Wait time is short!

        if wait_after_invoked >= 0:
            logger.debug(f"Integration: Waiting {wait_after_invoked} seconds before proceeding.")
            try:
                time.sleep(wait_after_invoked)
            except InterruptedError:
                logger.critical("Integration: wait_after_invoke was interrupted!")
                return False
        else:
            logger.debug(f"Integration: No waiting after integration start required.")
        
        if len(async_integrations) == 0:
            return None if len(sync_integrations) == 0 else True
        
        # 5. Before returning: Check if a process has failed already
        status = True
        for async_integration in async_integrations:
            logger.trace(f"Checking start status of async integration '{async_integration.obj.name}'")
            if async_integration.status.get_error() is not None:
                logger.critical(f"Integration: Integration '{async_integration.obj.name}' reported failure: {async_integration.status.get_error()}")
                async_integration.status.reset_error()
                status = False
        
        return status

    def has_error(self) -> bool:
        for integration in self._get_all_integration_wrappers():
            if integration.status.get_error() is not None:
                return True
                
        return False

    # Graceful shutdown
    def graceful_shutdown(self) -> None:
        logger.debug("Integration: Gracefully stopping all started integrations")

        # 1. Wait for async integrations to finish. They have to deal with timeouts themself.
        for integration in self._get_all_integration_wrappers():
            logger.trace(f"Checking start status of async integration '{integration.obj.name}'")

            if not integration.started:
                continue

            if integration.impl.is_integration_blocking():
                continue
            
            timeout = integration.impl.get_expected_timeout(at_shutdown=False)
            wait_for = (integration.started_at + timeout) - time.time()
            if wait_for < 0:
                wait_for = 0

            if not integration.status.get_finished_flag().is_set() and wait_for != 0:
                logger.info(f"Integration: Waiting for still running start phase of '{integration.obj.name}' to finish before shutdown (max. {wait_for:.2f} seconds)")

            try:
                if wait_for != 0:
                    integration.thread.join(wait_for)

                if integration.thread.is_alive():
                    logger.critical(f"Integration: Start phase of '{integration.obj.name}' timed out!")

                if integration.status.get_error() is not None:
                    logger.critical(f"Integration: Integration '{integration.obj.name}' reported failure.")
                    integration.status.reset_error()
            except InterruptedError:
                logger.critical("Integration: Waiting for integrations to finish start phase was interrupted!")
        
        # 2. Reset Status, get maximum Timeout & Invoke integration stop
        expected_max_timeout = 0
        for integration in self._get_all_integration_wrappers():
            integration.thread = None

            if not integration.started:
                logger.debug(f"Integration: '{integration.obj.name}' was not yet started, skipping stop phase.")
                continue

            if integration.is_shutdown:
                logger.debug(f"Integration: '{integration.obj.name}' was already stopped, skipping stop phase.")
                continue

            if integration.impl.get_expected_timeout(at_shutdown=True) > expected_max_timeout:
                    expected_max_timeout = integration.impl.get_expected_timeout(at_shutdown=True)
            integration.status.reset()
            self._stop_integration(integration)
            integration.is_shutdown = True

        # 3. Fire integration stop for all integrations
        # Stop is always sync
        wait_until = time.time() + expected_max_timeout + 1
        for integration in self._get_all_integration_wrappers():
            if integration.thread is None:
                logger.trace(f"Integration '{integration.obj.name}' was not stopped now.")
                continue

            try:
                logger.trace(f"Waiting for integration '{integration.obj.name}' to finish stop.")
                integration.thread.join(wait_until - time.time())
                if integration.thread.is_alive():
                    logger.critical(f"Integration: Timeout joining '{integration.obj.name}' stop thread.")
                    continue

                if integration.status.get_error() is not None:
                    logger.critical(f"Integration: Integration '{integration.obj.name}' reported failure.")
                    integration.status.reset_error()
            except InterruptedError:
                logger.critical("Integration: Waiting for integrations to finish stop phase was interrupted!")
                return
    
    # Force shutdown. Just fire stop action of integrations without waiting
    # Dont start threads here, since Python could be in shutdown at this stage.
    def force_shutdown(self) -> None:
        for integration in self._get_all_integration_wrappers():
            if not integration.started:
                logger.trace(f"Integration '{integration.obj.name}' was not started yet.")
                continue

            if integration.is_shutdown:
                logger.trace(f"Integration '{integration.obj.name}' was already stopped.")
                continue

            try:
                logger.debug(f"Integration: Forcefully stopping integration '{integration.obj.name}'")
                integration.status.reset_error()
                integration.impl.stop()
                if integration.status.get_error() is not None:
                    ex = integration.status.get_error()
                    logger.critical(f"Integration: Integration '{integration.obj.name}' reported failure: {ex}")
                    integration.status.reset_error()

            except Exception as ex:
                 logger.opt(exception=ex).critical(f"Integration: Unable to forcefully shutdown integration '{integration.obj.name}'")

    def dismantle(self, force: bool = False) -> None:
        if force:
            self.force_shutdown()
        else:
            self.graceful_shutdown()

    def get_name(self) -> str:
        return "IntegrationHelper"
