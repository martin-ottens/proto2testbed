import threading
import time

from loguru import logger
from typing import List, Optional
from dataclasses import dataclass

from utils.interfaces import Dismantable
from utils.settings import *
from integrations.base_integration import BaseIntegration, IntegrationStatusContainer
from integrations.await_integration import AwaitIntegration
from integrations.start_stop_integration import StartStopIntegration

@dataclass
class IntegrationExecutionWrapper:
    obj: Integration
    impl: BaseIntegration
    status: IntegrationStatusContainer
    thread: threading.Thread = None
    started_at: float = 0
    is_shutdown: bool = False

class IntegrationHelper(Dismantable):
    def __init__(self, integrations: List[Integration]) -> None:
        self.integrations = integrations

        self.mapped_integrations = {
            InvokeIntegrationAfter.INIT: [],
            InvokeIntegrationAfter.NETWORK: [],
            InvokeIntegrationAfter.STARTUP: []
        }

        for integration in integrations:
            integration_impl: BaseIntegration = None
            integration_status = IntegrationStatusContainer()

            match integration.mode:
                case IntegrationMode.AWAIT:
                    integration_impl = AwaitIntegration(integration.name,
                                                        integration.settings, 
                                                        integration_status, 
                                                        integration.environment)
                case IntegrationMode.STARTSTOP:
                    integration_impl = StartStopIntegration(integration.name,
                                                            integration.settings, 
                                                            integration_status, 
                                                            integration.environment)
                case _:
                    raise Exception(f"Unknown integration mode supplied: {integration.mode}")
            
            if not integration_impl.is_integration_ready():
                raise Exception(f"Integration {integration.name} cannot be started!")
            
            integration_impl[integration.invoke_after] = IntegrationExecutionWrapper(integration, integration_impl, integration_status)

    def _get_all_integration_wrappers(self) -> List[IntegrationExecutionWrapper]:
        result: List[IntegrationExecutionWrapper] = []
        for _, mapping in self.mapped_integrations.items():
            result.extend(mapping)

        return result

    def _fire_integration(exec: IntegrationExecutionWrapper, barrier: threading.Barrier):
        def integration_thread(exec: IntegrationExecutionWrapper, barrier: threading.Barrier):
            barrier.wait()
            exec.started_at = time.time()

            logger.trace(f"Calling start of integration '{exec.obj.name}'")
            try:
                exec.impl.start()

                if exec.status.get_error() is not None:
                    logger.error(f"Integration: Start of integration '{exec.obj.name} failed: {exec.status.get_error()}'")
            except Exception as ex:
                logger.opt(exception=ex).error(f"Integration: Start of {exec.obj.name} failed")
                exec.status.set_error(ex)

            exec.status.set_finished()
        
        exec.thread = threading.Thread(target=integration_thread, args=(exec, barrier, ), daemon=True)
        exec.thread.start()

    def _stop_integration(exec: IntegrationExecutionWrapper):
        def integration_thread(exec: IntegrationExecutionWrapper):
            exec.started_at = time.time()

            logger.trace(f"Calling stop of integration '{exec.obj.name}'")
            try:
                exec.impl.stop()

                if exec.status.get_error() is not None:
                    logger.error(f"Integration: Stop of integration '{exec.obj.name} failed: {exec.status.get_error()}'")
            except Exception as ex:
                logger.opt(exception=ex).error(f"Integration: Stop of {exec.obj.name} failed")
                exec.status.set_error(ex)
        
            exec.status.set_finished()
        
        exec.thread = threading.Thread(target=integration_thread, args=(exec, ), daemon=True)
        exec.thread.start()
    
    # Returns:
    # - None = No integration fired
    # - True = All integrations okay
    # - False = At least one integration failed at invoke
    def handle_stage_start(self, stage: InvokeIntegrationAfter) -> Optional[bool]:

        # 1. Find integrations to be invoked at this stage
        fire_integrations: List[IntegrationExecutionWrapper] = self.mapped_integrations[InvokeIntegrationAfter]

        if fire_integrations is None or len(fire_integrations) == 0:
            return None
        
        if SettingsWrapper.cli_paramaters.skip_integration:
            for integration in fire_integrations:
                logger.warning(f"Integration: Start of '{integration.obj.name}' integration at stage {stage.upper()} skipped.")
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
            wait_until = int((time.time() + expected_max_timeout + 1) * 2)
            logger.debug(f"Integration: Waiting {expected_max_timeout} seconds for start stage of blocking integrations to finish!")
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
                logger.critical("Integration: At least one integration start stage in blocking mode failed")
                return False

        # 4. Fire all non-blocking integrations
        if len(async_integrations) != 0:
            async_barrier = threading.Barrier(len(async_integrations) + 1)

            for async_integration in async_integrations:
                self._fire_integration(async_integration, async_barrier)

            async_barrier.wait() # No interrupt handling -> Wait time is short!

        logger.debug(f"Integration: Waiting {wait_after_invoked} seconds before proceeding!")
        try:
            time.sleep(wait_after_invoked)
        except InterruptedError:
            logger.critical("Integration: wait_after_invoke was interrupted!")
            return False
        
        if len(async_integrations) == 0:
            return None if len(sync_integrations) == 0 else True
        
        # 5. Before returning: Check if a process has failed already
        status = True
        for async_integration in async_integrations:
            logger.trace(f"Checking start status of async integration '{async_integration.obj.name}'")
            if async_integration.status.get_error() is not None:
                logger.critical(f"Integration: Integration '{async_integration.obj.name}' reported failure.")
                async_integration.status.reset_error()
                status = False
        
        return status

    def has_error(self) -> bool:
        for integration in self._get_all_integration_wrappers():
            if integration.status.get_error() is not None:
                return True
                
        return False

    # Graceful shutdown
    def shutdown(self) -> None:
        # 1. Wait for async integrations to finish. They have to deal with timeouts themself.
        for integration in self._get_all_integration_wrappers():
            logger.trace(f"Checking start status of async integration '{integration.obj.name}'")
            if integration.impl.is_integration_blocking():
                continue
            
            timeout = integration.impl.get_expected_timeout(at_shutdown=False)
            wait_for = (integration.started_at + timeout) - time.time()
            if wait_for <= 0:
                wait_for = 1

            if not integration.status.get_finished_flag().is_set():
                logger.info(f"Integration: Waiting for start stage of '{integration.obj.name}' to finish (max. {wait_for} seconds)")

            try:
                integration.thread.join(wait_for + 1)

                if integration.thread.is_alive():
                    logger.critical(f"Integration: Start stage of '{integration.obj.name}' timed out!")

                if integration.status.get_error() is not None:
                    logger.critical(f"Integration: Integration '{integration.obj.name}' reportted failure.")
                    integration.status.reset_error()
            except InterruptedError:
                logger.critical("Integration: Waiting for integrations to finish start stage was interrupted!")
        
        # 2. Reset Status, get maximum Timeout & Invoke integration stop
        expected_max_timeout = 0
        for integration in self._get_all_integration_wrappers():
            integration.thread = None

            if integration.is_shutdown:
                logger.debug(f"Integration: '{integration.obj.name}' was already stopped, skipping stop stage.")
                continue

            if integration.impl.get_expected_timeout(at_shutdown=True) > expected_max_timeout:
                    expected_max_timeout = integration.impl.get_expected_timeout(at_shutdown=True)
            integration.status.reset()
            self._stop_integration(integration)
            integration.is_shutdown = True

        # 3. Fire integration stop for all integrations
        # Stop is always sync
        wait_until = int((time.time() + expected_max_timeout + 1) * 2)
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
                logger.critical("Integration: Waiting for integrations to finish stop stage was interrupted!")
                return

    # Force shutdown. Just fire stop action of integrations without waiting
    # Dont start threads here, since Python could be in shutdown at this stage.
    def dismantle(self) -> None:
        for integration in self._get_all_integration_wrappers():
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

    def get_name(self) -> str:
        return "IntegrationHelper"
