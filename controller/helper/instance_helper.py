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

import pexpect
import hashlib
import tempfile
import os
import sys
import ipaddress

from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from loguru import logger
from typing import Optional
from dataclasses import dataclass

from utils.interfaces import Dismantable
from utils.system_commands import invoke_subprocess, invoke_pexpect, get_asset_relative_to, get_DNS_resolver
from state_manager import InstanceState
from utils.settings import CommonSettings
from utils.networking import InstanceInterface
from constants import SUPPORTED_EXTRA_NETWORKS_PER_INSTANCE

@dataclass
class InstanceManagementSettings():
    interface: InstanceInterface
    ip_interface: ipaddress.IPv4Interface
    gateway: str


class InstanceHelper(Dismantable):
    __QEMU_NIC_TEMPLATE     = "-nic tap,model={model},ifname={tapname},mac={mac} "
    __QEMU_COMMAND_TEMPLATE = """qemu-system-x86_64 \
                                -boot c \
                                -m {memory} \
                                {kvm} \
                                -smp {cores} \
                                -machine q35 \
                                -hda {image} \
                                -serial unix:{tty},server,nowait \
                                -chardev socket,id=mgmtchardev,path={serial},server,nowait \
                                -device pci-serial,chardev=mgmtchardev \
                                -virtfs local,path={mount},mount_tag=exchange,security_model=passthrough,id=exchange \
                                -virtfs local,path={testbed_package},mount_tag=tbp,security_model=passthrough,id=tbp,readonly=on \
                                {nics} \
                                -snapshot \
                                -cdrom {cloud_init_iso} \
                                -display none \
                                -monitor stdio"""
    __QEMU_KVM_OPTIONS = """-enable-kvm \
                            -cpu host"""
    __CLOUD_INIT_ISO_TEMPLATE = """genisoimage \
                                   -output {output} \
                                   -volid cidata \
                                   -joliet \
                                   -rock {input}"""

    def __init__(self, instance: InstanceState, 
                 management: Optional[InstanceManagementSettings],
                 image: str, testbed_package_path: str,
                 cores: int = 2, memory: int = 1024, debug: bool = False, 
                 disable_kvm: bool = False, netmodel: str = "virtio") -> None:
        self.instance = instance
        self.debug = debug
        self.qemu_handle = None
        self.testbed_package_path = testbed_package_path

        if len(instance.interfaces) > (SUPPORTED_EXTRA_NETWORKS_PER_INSTANCE + 1):
            raise Exception(f"Error during creation, {SUPPORTED_EXTRA_NETWORKS_PER_INSTANCE} interfaces are allowed, but {len(extra_interfaces)} were added!")
        
        if not instance.interchange_ready:
            raise Exception("Unable to set up interchange directory for p9 an mgmt socket!")

        self.tempdir = tempfile.TemporaryDirectory()
 
        try:
            # Generate pseudo unique interface macs
            hash_hex = hashlib.sha256((CommonSettings.unique_run_name + instance.name).encode()).hexdigest()
            base_mac = hash_hex[1:2] + 'e:' + hash_hex[2:4] + ':' + hash_hex[4:6] + ':' + hash_hex[6:8] + ':' + hash_hex[8:10] + ':' + hash_hex[10:11]
            interfaces_command = ""
            experiment_interfaces = []

            if management is not None:
                mac = (base_mac + str(management.interface.tap_index))
                instance.set_interface_mac(management.interface.bridge_name, mac)
                management.interface.interface_on_instance = "mgmt"
                interfaces_command += InstanceHelper.__QEMU_NIC_TEMPLATE.format(model=netmodel, tapname=management.interface.tap_dev, mac=mac)

            eth_index = 1
            for interface in instance.interfaces:
                if interface.is_management_interface:
                    continue

                mac = (base_mac + str(interface.tap_index))
                instance.set_interface_mac(interface.bridge_name, mac)
                interface.interface_on_instance = f"eth{eth_index}"
                experiment_interfaces.append({
                    "dev": interface.interface_on_instance,
                    "mac": mac
                })
                interfaces_command += InstanceHelper.__QEMU_NIC_TEMPLATE.format(model=netmodel, tapname=interface.tap_dev, mac=mac)
                eth_index += 1

            # Generate cloud-init files
            init_files = Path(self.tempdir.name) / "cloud-init"
            os.mkdir(init_files)

            j2_env = Environment(loader=FileSystemLoader(get_asset_relative_to(__file__, "../vm_templates/")))

            meta_data = j2_env.get_template("meta-data.j2").render()
            with open(init_files / "meta-data", mode="w", encoding="utf-8") as handle:
                handle.write(meta_data)

            domain_parts = instance.name.split('.')
            fqdn = "\"\""
            if len(domain_parts) > 2:
                fqdn = "\"" + '.'.join(domain_parts[1:]) + "\""
            
            user_data = j2_env.get_template("user-data.j2").render(
                hostname=instance.name,
                fqdn=fqdn,
                dns_primary=get_DNS_resolver()
            )
            with open(init_files / "user-data", mode="w", encoding="utf-8") as handle:
                handle.write(user_data)

            network_config = None
            if management is not None:
                network_config = j2_env.get_template("network-config-default.j2").render(
                    mgmt_address=str(management.ip_interface.ip),
                    mgmt_server=str(management.gateway),
                    mgmt_netmask=management.ip_interface.with_prefixlen.split("/")[1],
                    mgmt_if_mac=management.interface.tap_mac,
                    experiment_interfaces=experiment_interfaces
                )
            else:
                network_config = j2_env.get_template("network-config-no-mgmt.j2").render(
                    experiment_interfaces=experiment_interfaces
                )

            with open(init_files / "network-config", mode="w", encoding="utf-8") as handle:
                handle.write(network_config)

            cloud_init_iso = str(Path(self.tempdir.name) / "cloud-init.iso")
            process = invoke_subprocess([InstanceHelper.__CLOUD_INIT_ISO_TEMPLATE.format(input=init_files, output=cloud_init_iso)],
                                        shell=True)
            
            if process.returncode != 0:
                raise Exception(f"Unbale to run genisoimage: {process.stderr.decode('utf-8')}")

            # Prepare qemu command
            self.qemu_command = InstanceHelper.__QEMU_COMMAND_TEMPLATE.format(
                memory=memory,
                cores=cores,
                image=image,
                nics=interfaces_command,
                cloud_init_iso=cloud_init_iso,
                serial=self.instance.get_mgmt_socket_path(),
                tty=self.instance.get_mgmt_tty_path(),
                mount=self.instance.get_p9_data_path(),
                testbed_package=self.testbed_package_path,
                kvm=(InstanceHelper.__QEMU_KVM_OPTIONS if not disable_kvm else '')
            )
        except Exception as ex:
            self.tempdir.cleanup()
            self.qemu_handle = None
            self.qemu_command = None
            raise ex

    def destory_instance(self, force: bool = False):
        self.stop_instance(force)
        self.tempdir.cleanup()

    def __del__(self):
        self.destory_instance(True)
    
    def dismantle(self, force: bool = False) -> None:
        self.destory_instance(force)

    def dismantle_parallel(self) -> bool:
        return True

    def get_name(self) -> str:
        return f"Instance {self.instance.name}"

    def ready_to_start(self) -> bool:
        return self.qemu_command is not None and self.qemu_handle is None

    def start_instance(self) -> bool:
        if self.qemu_handle is not None:
            return False

        logger.debug(f"Instance '{self.instance.name}': Starting instance ...")
        try:
            self.qemu_handle = invoke_pexpect(self.qemu_command, needs_root=True)
            if self.debug:
                self.qemu_handle.logfile = sys.stdout
            self.qemu_handle.expect_exact("(qemu)", timeout=10)
        except pexpect.EOF as ex:
            raise Exception(f"Unable to start Instance '{self.instance.name}', process exited unexpected") from ex
        except pexpect.TIMEOUT as ex:
            raise Exception(f"Unable to start Instance '{self.instance.name}', timeout during QEMU start") from ex
        logger.info(f"Instance '{self.instance.name}': Instance was started!")
        return True

    def stop_instance(self, force: bool = False) -> bool:
        if self.qemu_handle is None:
            return False

        logger.debug(f"Instance '{self.instance.name}': Stopping instance ...")
        try:
            self.qemu_handle.sendline("system_powerdown")
            if not force:
                self.qemu_handle.expect(pexpect.EOF, timeout=30)
        except pexpect.TIMEOUT as ex:
            if force and not self.qemu_command.terminated:
                logger.info(f"Instance '{self.instance.name}': Force terminating instance ...")
                self.qemu_handle.terminate()
                if not self.qemu_handle.terminated:
                    raise Exception(f"Unable to terminate Instance '{self.instance.name}'")
            else:
                self.qemu_handle.terminate()
                raise Exception(f"Unable to stop Instance {self.instance.name}, timeout occured:") from ex
        finally:
            self.qemu_handle = None

        logger.info(f"Instance '{self.instance.name}': Instance was stopped!")
        return True

    def instance_status(self) -> str:
        if self.qemu_handle is None:
            return "VM satus: inactive"
        try:
            self.qemu_handle.sendline("info status")
            self.qemu_handle.readline()
            status = self.qemu_handle.readline().strip()
            self.qemu_handle.expect_exact("(qemu)", timeout=1)
            return status
        except Exception as ex:
            logger.opt(exception=ex).warning(f"Instance '{self.instance.name}': Unable to get status")
            return "VM status: unkown"
