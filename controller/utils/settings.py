from typing import List, Dict
from dataclasses import dataclass

from common.collector_configs import ExperimentConfig

@dataclass
class TestbedSettings():
    machines_internet_access: bool = True
    auto_dismantle_seconds: int = 180
    management_network: str = "172.16.99.0/24"

@dataclass
class TestbedNetwork():
    name: str
    physical_ports: List[str] = None


class TestbedMachine():
    def __init__(self, name: str, diskimage: str, setup_script: str = None, 
                 environment: Dict[str, str]=  None, cores: int = 2, 
                 memory: int = 1024, networks: List[str] = None,
                 collectors = None) -> None:
        self.name: str = name
        self.diskimage: str = diskimage
        self.setup_script: str = setup_script
        self.environment: Dict[str, str] = environment
        self.cores: int = cores
        self.memory: int = memory
        self.networks: List[str] = networks

        self.experiments: List[ExperimentConfig] = []

        if collectors is None:
            return

        for experiment in collectors:
            self.experiments.append(ExperimentConfig(**experiment))


class TestbedConfig():
    def __init__(self, json) -> None:
        self.settings: TestbedSettings = TestbedSettings(json["settings"])
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
        self.clean: bool = False


class SettingsWrapper():
    cli_paramaters: CLIParameters = None
    testbed_config: TestbedConfig = None
