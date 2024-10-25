from typing import List, Dict, Optional, Any
from enum import Enum
from abc import ABC
from dataclasses import dataclass

from common.application_configs import ApplicationConfig

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

@dataclass
class AwaitIntegrationSettings(IntegrationSettings):
    start_script: str
    wait_for_exit: int
    start_delay: int = 0

@dataclass
class StartStopIntegrationSettings(IntegrationSettings):
    start_script: str
    stop_script: str
    wait_for_exit: int = 5
    start_delay: int = -1

@dataclass
class NS3IntegrationSettings(IntegrationSettings):
    basepath: str
    program: str
    interfaces: List[str]
    wait: bool = False
    fail_on_exist: bool = False
    args: Optional[Dict[str, str]] = None

class IntegrationMode(Enum):
    AWAIT = "await"
    STARTSTOP = "startstop"
    NS3_EMULATION = "ns3-emulation"

    def __str__(self):
        return str(self.value)
    
class InvokeIntegrationAfter(Enum):
    STARTUP = "startup"
    NETWORK = "network"
    INIT = "init"

    def __str__(self):
        return str(self.value)
    
class Integration():
    def __init__(self, name: str, mode: str, environment: Optional[Dict[str, str]] = None,
                 invoke_after: str = str(InvokeIntegrationAfter.STARTUP), wait_after_invoke: int = 0,
                 settings: Optional[Any] = None) -> None:

        self.name = name
        self.mode: IntegrationMode = IntegrationMode(mode)
        self.environment = environment
        self.invoke_after: InvokeIntegrationAfter = InvokeIntegrationAfter(invoke_after)
        self.wait_after_invoke = wait_after_invoke
        self.settings: IntegrationSettings

        match self.mode:
            case IntegrationMode.AWAIT:
                self.settings = AwaitIntegrationSettings(**settings)
            case IntegrationMode.STARTSTOP:
                self.settings = StartStopIntegrationSettings(**settings)
            case IntegrationMode.NS3_EMULATION:
                self.settings = NS3IntegrationSettings(**settings)
            case _:
                raise Exception(f"Unkown integration mode {mode}")

class TestbedInstance():
    def __init__(self, name: str, diskimage: str, setup_script: str = None, 
                 environment: Dict[str, str]=  None, cores: int = 2, 
                 memory: int = 1024, networks: List[str] = None,
                 netmodel: str = "virtio", applications = None) -> None:
        self.name: str = name
        self.diskimage: str = diskimage
        self.setup_script: str = setup_script
        self.environment: Dict[str, str] = environment
        self.cores: int = cores
        self.memory: int = memory
        self.networks: List[str] = networks
        self.netmodel: str = netmodel

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


@dataclass
class CLIParameters():
    config: Optional[str] = None
    pause: Optional[str] = None
    wait: Optional[int] = None
    sudo_mode: bool = False
    disable_kvm: bool = False
    clean: bool = False
    experiment: Optional[str] = None
    dont_use_influx: Optional[bool] = False
    influx_path: Optional[str] = None
    skip_integration: bool = False
    skip_substitution: bool = False
    preserve: Optional[str] = None


class SettingsWrapper():
    cli_paramaters: CLIParameters = None
    testbed_config: TestbedConfig = None
