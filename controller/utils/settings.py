from typing import List, Dict, Optional, Any
from enum import Enum
from abc import ABC
from dataclasses import dataclass

from common.collector_configs import ExperimentConfig

@dataclass
class TestbedSettings():
    machines_internet_access: bool = True
    management_network: str = "172.16.99.0/24"

@dataclass
class TestbedNetwork():
    name: str
    physical_ports: List[str] = None

class IntegrationSettings(ABC):
    pass

@dataclass
class NoneIntegrationSettings(IntegrationSettings):
    pass

@dataclass
class AwaitIntegrationSettings(IntegrationSettings):
    start_script: str
    wait_for_exit: int

@dataclass
class StartStopIntegrationSettings(IntegrationSettings):
    start_script: str
    stop_script: str
    wait_for_exit: int = 5

class IntegrationMode(Enum):
    NONE = "none"
    AWAIT = "await"
    STARTSTOP = "startstop"

    def __str__(self):
        return str(self.value)
    
class InvokeIntegrationAfter(Enum):
    STARTUP = "startup"
    NETWORK = "network"
    INIT = "init"

    def __str__(self):
        return str(self.value)
    
class Integration():
    def __init__(self, mode: str, environment: Optional[Dict[str, str]] = None,
                 invoke_after: str = str(InvokeIntegrationAfter.STARTUP), wait_after_invoke: str = 0,
                 settings: Optional[Any] = None) -> None:

        self.mode: IntegrationMode = IntegrationMode(mode)
        self.environment = environment
        self.invoke_after: InvokeIntegrationAfter = InvokeIntegrationAfter(invoke_after)
        self.wait_after_invoke = wait_after_invoke
        self.settings: IntegrationSettings

        match self.mode:
            case IntegrationMode.NONE:
                self.settings = NoneIntegrationSettings(**settings)
            case IntegrationMode.AWAIT:
                self.settings = AwaitIntegrationSettings(**settings)
            case IntegrationMode.STARTSTOP:
                self.settings = StartStopIntegrationSettings(**settings)
            case _:
                raise Exception(f"Unkown integration mode {mode}")

class TestbedMachine():
    def __init__(self, name: str, diskimage: str, setup_script: str = None, 
                 environment: Dict[str, str]=  None, cores: int = 2, 
                 memory: int = 1024, networks: List[str] = None,
                 netmodel: str = "virtio", collectors = None) -> None:
        self.name: str = name
        self.diskimage: str = diskimage
        self.setup_script: str = setup_script
        self.environment: Dict[str, str] = environment
        self.cores: int = cores
        self.memory: int = memory
        self.networks: List[str] = networks
        self.netmodel: str = netmodel

        self.experiments: List[ExperimentConfig] = []

        if collectors is None:
            return

        for experiment in collectors:
            self.experiments.append(ExperimentConfig(**experiment))


class TestbedConfig():
    def __init__(self, json) -> None:
        self.settings: TestbedSettings = TestbedSettings(**json["settings"])
        self.integration: Integration = Integration(**json["integration"])
        self.networks: List[TestbedNetwork] = []
        self.machines: List[TestbedMachine] = []

        for network in json["networks"]:
            self.networks.append(TestbedNetwork(**network))
        
        for machine in json["machines"]:
            self.machines.append(TestbedMachine(**machine))


class CLIParameters():
    def __init__(self) -> None:
        self.config: str = None
        self.pause: str = None
        self.wait: int = None
        self.sudo_mode: bool = False
        self.disable_kvm: bool = False
        self.clean: bool = False
        self.experiment: str = None
        self.dont_use_influx: bool = False
        self.influx_path: str = None
        self.skip_integration: bool = False
        self.skip_substitution: bool = False


class SettingsWrapper():
    cli_paramaters: CLIParameters = None
    testbed_config: TestbedConfig = None
