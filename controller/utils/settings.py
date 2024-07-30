from typing import List, Dict

from common.collector_configs import ExperimentConfig

class TestbedSettings():
    def __init__(self, json) -> None:
        self.machines_internet_access: bool = True
        self.auto_dismantle_seconds: int = 180
        self.management_network: str = "172.16.99.0/24"

        self.__dict__.update(json)


class TestbedNetwork():
    def __init__(self, json) -> None:
        self.name: str = None
        self.physical_ports: List[str] = None

        self.__dict__.update(json)


class TestbedMachine():
    def __init__(self, json) -> None:
        self.name: str = None
        self.diskimage: str = None
        self.setup_script: str = None
        self.environment: Dict[str, str] = None
        self.cores: int = 2
        self.memory: int = 1024
        self.networks: List[str] = None

        self.__dict__.update(json)

        self.experiments: List[ExperimentConfig] = []

        if self.collectors is None:
            return

        for experiment in self.collectors:
            self.experiments.append(ExperimentConfig(experiment))


class TestbedConfig():
    def __init__(self, json) -> None:
        self.settings: TestbedSettings = TestbedSettings(json["settings"])
        self.networks: List[TestbedNetwork] = []
        self.machines: List[TestbedMachine] = []

        for network in json["networks"]:
            self.networks.append(TestbedNetwork(network))
        
        for machine in json["machines"]:
            self.machines.append(TestbedMachine(machine))


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
