import os
import json

from typing import List, Dict, Optional, Any
from enum import Enum
from abc import ABC
from dataclasses import dataclass
from pathlib import Path
from loguru import logger

from common.application_configs import ApplicationConfig
from utils.continue_mode import PauseAfterSteps


@dataclass
class TestbedSettings():
    management_network: Optional[str] = None
    diskimage_basepath: str = "./"
    startup_init_timeout: int = 30
    experiment_timeout: int = -1


@dataclass
class TestbedNetwork():
    name: str
    host_ports: List[str] = None


class IntegrationSettings(ABC):
    pass
    

class InvokeIntegrationAfter(Enum):
    STARTUP = "startup"
    NETWORK = "network"
    INIT = "init"

    def __str__(self):
        return str(self.value)
    

class Integration():
    def __init__(self, name: str, type: str, environment: Optional[Dict[str, str]] = None,
                 invoke_after: str = str(InvokeIntegrationAfter.STARTUP), wait_after_invoke: int = 0,
                 settings: Optional[Any] = None) -> None:

        self.name = name
        self.type = type
        self.environment = environment
        self.invoke_after: InvokeIntegrationAfter = InvokeIntegrationAfter(invoke_after)
        self.wait_after_invoke = wait_after_invoke
        self.settings: IntegrationSettings = settings


class TestbedInstance():
    def __init__(self, name: str, diskimage: str, setup_script: str = None, 
                 environment: Optional[Dict[str, str]] =  None, cores: int = 2, 
                 memory: int = 1024, networks: Optional[List[str]] = None,
                 netmodel: str = "virtio", applications = None, 
                 preserve_files: Optional[List[str]] = None) -> None:
        self.name: str = name
        self.diskimage: str = diskimage
        self.setup_script: str = setup_script
        self.environment: Dict[str, str] = environment
        self.cores: int = cores
        self.memory: int = memory
        self.networks: List[str] = networks
        self.netmodel: str = netmodel
        self.preserve_files: List[str] = preserve_files

        self.applications: List[ApplicationConfig] = []

        if applications is None:
            return

        for application in applications:
            self.applications.append(ApplicationConfig(**application))


class TestbedConfig():
    def __init__(self, json) -> None:
        self.settings: TestbedSettings = TestbedSettings(**json["settings"])
        self.networks: List[TestbedNetwork] = []
        self.instances: List[TestbedInstance] = []
        self.integrations: List[Integration] = []

        for network in json["networks"]:
            self.networks.append(TestbedNetwork(**network))
        
        for integration in json["integrations"]:
            self.integrations.append(Integration(**integration))

        for machine in json["instances"]:
            self.instances.append(TestbedInstance(**machine))


class DefaultConfigs():
    def __init__(self, path: str):
        self.defaults = {}
        if not os.path.exists(path):
            logger.debug(f"No default config in path '{path}'")
        
        with open(path, "r") as handle:
            self.defaults = json.load(handle)

    def get_defaults(self, key: str):
        if self.defaults is None or key not in self.defaults.keys():
            logger.debug(f"No default value for key '{key}' provided in config.")
            return None
        else:
            return self.defaults.get(key)


@dataclass
class CLIParameters():
    config: Optional[str] = None
    interact: PauseAfterSteps = PauseAfterSteps.DISABLE
    sudo_mode: bool = False
    disable_kvm: bool = False
    experiment: Optional[str] = None
    dont_use_influx: Optional[bool] = False
    influx_path: Optional[str] = None
    skip_integration: bool = False
    skip_substitution: bool = False
    preserve: Optional[str] = None
    log_verbose: int = 0
    app_base_path: Path = None


class SettingsWrapper():
    cli_paramaters: Optional[CLIParameters] = None
    testbed_config: Optional[TestbedConfig] = None
    default_configs: Optional[DefaultConfigs] = None
    experiment: Optional[str] = None
    executor: Optional[int] = None
    cmdline: Optional[str] = None
    main_pid: Optional[int] = None
    unique_run_name: Optional[str] = None
