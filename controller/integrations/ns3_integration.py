import json

from typing import Dict, Optional
from multiprocessing import Process
from loguru import logger

from utils.settings import IntegrationSettings, NS3IntegrationSettings
from utils.system_commands import invoke_subprocess
from integrations.base_integration import BaseIntegration, IntegrationStatusContainer

class NS3Integration(BaseIntegration):
    def __init__(self, name: str, settings: IntegrationSettings, status_container: IntegrationStatusContainer, environment: Optional[Dict[str, str]] = None) -> None:
        super().__init__(name, settings, status_container, environment)
        if not isinstance(settings, NS3IntegrationSettings):
            raise Exception("Received invalid settings type!")
        
        self.settings: NS3IntegrationSettings = settings
        self.process = None

    def is_integration_ready(self) -> bool:
        return True

    def is_integration_blocking(self) -> bool:
        return False
    
    def get_expected_timeout(self, at_shutdown: bool = False) -> int:
        return 300 if at_shutdown else 0

    def start(self) -> bool:
        # 0. Search for existing interfaces
        sub_process = invoke_subprocess(["/usr/sbin/ip", "--json", "--details", "link", "show"])
        if sub_process.returncode != 0:
            self.status.set_error(f"Unable to check for existing interfaces: {sub_process.stderr.decode('utf-8')}")
            return False
        
        interface_list = json.loads(sub_process.stdout.decode("utf-8"))
        for interface in interface_list:
            if interface["ifname"] in self.settings.interfaces:
                if self.settings.fail_on_exist:
                    self.status.set_error(f"Interface '{interface['ifname']}' already exists.")
                    return False
                
                if interface["linkinfo"]["type"] != "tap":
                    self.status.set_error(f"Interface with name '{interface['ifname']}' already exists, but its not tap.")
                    return False
                
                # Not managed by us, so don't touch.
                logger.warning(f"ns-3 Integration {self.name}: Ignoring existing interface {interface['ifname']}")
                self.settings.interfaces.remove(interface["ifname"])

        # 1. Create new interfaces
        for interface in self.settings.interfaces:
            try:
                sub_process = invoke_subprocess(["/usr/sbin/ip", "tuntap", "add", interface, "mode", "tap"])
                if sub_process.returncode != 0:
                    self.status.set_error(f"Unable to create tap interface '{interface}': {sub_process.stderr.decode('utf-8')}")
                    return False
                
                sub_process = invoke_subprocess(["/usr/sbin/ip", "link", "set", "up", "dev", interface])
                if sub_process.returncode != 0:
                    self.status.set_error(f"Unable to set link '{interface}' up: {sub_process.stderr.decode('utf-8')}")
                    return False
            except Exception as ex:
                self.status.set_error(f"Unable to configure tap interface '{interface}': {ex}")
                return False

        # 2. Start ns-3
        ns_3_command = f"cd {self.settings.basepath} && ./ns3 run {self.settings.program} --no-build"
        if self.settings.args is not None and len(self.settings.args) > 0:
            ns_3_command += " -- "
            for k, v in self.settings.args.items():
                ns_3_command += f"--{k}={v}"

        self.process = Process(target=self.run_subprocess, args=(ns_3_command, True, None, ))
        self.process.start()
        return True

    def stop(self) -> bool:
        try:
            if self.process is not None and self.process.is_alive():
                if self.settings.wait:
                    logger.info(f"ns-3 Integration {self.name}: Waiting for ns-3 process '{self.name}' to terminate")
                    self.process.join()
                else:
                    logger.info(f"ns-3 Integration {self.name}: Killing ns-3 process '{self.name}' without waiting")
                    self.kill_process_with_child(self.process)
        except Exception as ex:
            self.status.set_error(f"Error during stop of ns-3 process '{self.name}' - skipping interface deletion: {ex}")
            return False
        
        got_error = False
        for interface in self.settings.interfaces:
            try:
                sub_process = invoke_subprocess(["/usr/sbin/ip", "link", "del", interface])
                if sub_process.returncode != 0:
                    logger.error(f"ns-3 Integration {self.name}: Unable to delete tap interface '{interface}': {sub_process.stderr.decode('utf-8')}")
                    got_error = True

            except Exception as ex:
                logger.opt(exception=ex).error(f"ns-3 Integration {self.name}: Error deleting tap interface '{interface}'")
                got_error = True

        if got_error:
            self.status.set_error(f"At least one tap interface could not be deleted!")
            return False
        else:
            return True
