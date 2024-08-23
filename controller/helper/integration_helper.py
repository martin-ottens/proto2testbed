import threading
import time

from loguru import logger
from typing import List, Tuple, Optional
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

    def _fire_integration_sync(exec: IntegrationExecutionWrapper) -> bool:
        # CRTL+C Interrupt handling required here!
        pass
    
    # Important: Integration must take care itself about all timeouts. This thread
    # will not handle any timeouts!
    def _fire_integration_async(exec: IntegrationExecutionWrapper, barrier: threading.Barrier):
        pass
    
    # Returns:
    # - None = No integration fired
    # - True = All integrations okay
    # - False = At least one integration failed at invoke
    def handle_stage_start(self, stage: InvokeIntegrationAfter) -> Optional[bool]:
        fire_integrations: List[IntegrationExecutionWrapper] = self.mapped_integrations[InvokeIntegrationAfter]

        if fire_integrations is None or len(fire_integrations) == 0:
            return None
        
        if SettingsWrapper.cli_paramaters.skip_integration:
            for integration in fire_integrations:
                logger.warning(f"Integration: Start of '{integration[0].name}' integration at stage {stage.upper()} skipped.")
            return None
        
        # 1. Find all blocking integrations, fire them synchronsly with timeout
        # 2. All non-blocking integrations: Fire threads with barrier
        # 3. Find integration with largest wait_after_invoke -> wait time
        # 4. Before returning: Check if a Process already reported an error 

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
        
        for sync_integration in sync_integrations:
            if not self._fire_integration_sync(sync_integration):
                logger.critical(f"Integration: Error running start of integration '{sync_integration.obj.name}'.")
                return False
            else:
                logger.success(f"Integration: Integration start of '{sync_integration.obj.name}' successfully executed.")

        if len(async_integrations) == 0:
            return False

        barrier = threading.Barrier(len(async_integrations) + 1)

        for async_integration in async_integrations:
            self._fire_integration_async(async_integration, barrier)

        # No interrupt handling -> Wait time is short!
        barrier.wait()

        logger.debug(f"Integration: Waiting {wait_after_invoked} seconds before proceeding!")
        try:
            time.sleep(wait_after_invoked)
        except InterruptedError:
            logger.critical("Integration: wait_after_invoke was interrupted!")
            return False
        
        status = True
        for async_integration in async_integrations:
            if async_integration.status.get_error() is not None:
                logger.critical(f"Integration: {async_integration.obj.name} failed: {async_integration.status.get_error()}")
        
        return status

    def has_error(self) -> bool:
        pass

    def dismantle(self) -> None:
        if self.dismantle_action is not None:
            try:
                self.dismantle_action(self.dismantle_context)
                logger.success("Integration: Integration was stopped.")
            except Exception as ex:
                logger.opt(exception=ex).error("Integration: Unable to top integtation!")
            self.dismantle_action = None

    def get_name(self) -> str:
        return "IntegrationHelper"
