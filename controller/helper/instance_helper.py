import pexpect
import hashlib
import tempfile
import os
import sys

from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from loguru import logger
from typing import List, Dict

from utils.interfaces import Dismantable
from utils.system_commands import invoke_subprocess, invoke_pexpect, get_asset_relative_to, get_DNS_resolver
from state_manager import MachineState
from utils.settings import SettingsWrapper

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
                                -virtfs local,path={testbed_package},mount_tag=tbp,security_model=passthrough,id=tbp,readonly \
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

    def __init__(self, instance: MachineState, management: Dict[str, str],
                 extra_interfaces: List[str], image: str, testbed_package_path: str,
                 cores: int = 2, memory: int = 1024, debug: bool = False, 
                 disable_kvm: bool = False, netmodel: str = "virtio") -> None:
        self.instance = instance
        self.debug = debug
        self.qemu_handle = None
        self.testbed_package_path = testbed_package_path

        if management is not None:
            if not all(key in management for key in ["interface", "ip", "gateway"]):
                raise Exception(f"Error during creation, management config is not correct!")

            self.ip_address = management["ip"].ip

        if len(extra_interfaces) > 4:
            raise Exception(f"Error during creation, 4 interfaces are allowed, but {len(extra_interfaces)} were added!")
        
        if not instance.interchange_ready:
            raise Exception("Unable to set up interchange directory for p9 an mgmt socket!")

        self.tempdir = tempfile.TemporaryDirectory()
 
        # Generate cloud-init files
        try:
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

            if management is not None:
                network_config = j2_env.get_template("network-config.j2").render(
                    mgmt_address=str(management["ip"].ip),
                    mgmt_server=str(management["gateway"]),
                    mgmt_netmask=management["ip"].with_prefixlen.split("/")[1]
                )
                with open(init_files / "network-config", mode="w", encoding="utf-8") as handle:
                    handle.write(network_config)

            cloud_init_iso = str(Path(self.tempdir.name) / "cloud-init.iso")
            process = invoke_subprocess([InstanceHelper.__CLOUD_INIT_ISO_TEMPLATE.format(input=init_files, output=cloud_init_iso)],
                                        shell=True)
            
            if process.returncode != 0:
                raise Exception(f"Unbale to run genisoimage: {process.stderr.decode('utf-8')}")
            
            # Generate pseudo unique interface macs
            hash_hex = hashlib.sha256((SettingsWrapper.cli_paramaters.unique_run_name + instance.name).encode()).hexdigest()
            base_mac = hash_hex[1:2] + 'e:' + hash_hex[2:4] + ':' + hash_hex[4:6] + ':' + hash_hex[6:8] + ':' + hash_hex[8:10] + ':' + hash_hex[10:11]
            
            interfaces = ""
            if management is not None:
                interfaces += InstanceHelper.__QEMU_NIC_TEMPLATE.format(model=netmodel, tapname=management["interface"], mac=(base_mac + "0"))

            for index, name in enumerate(extra_interfaces):
                interfaces += InstanceHelper.__QEMU_NIC_TEMPLATE.format(model=netmodel, tapname=name, mac=(base_mac + str(index + 1)))

            # Prepare qemu command
            self.qemu_command = InstanceHelper.__QEMU_COMMAND_TEMPLATE.format(
                memory=memory,
                cores=cores,
                image=image,
                nics=interfaces,
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

    def _destory_instance(self):
        self.stop_instance()
        self.tempdir.cleanup()

    def __del__(self):
        self._destory_instance()
    
    def dismantle(self) -> None:
        self._destory_instance()

    def dismantle_parallel(self) -> bool:
        return True

    def get_name(self) -> str:
        return f"VirtualMachine {self.instance.name}"

    def ready_to_start(self) -> bool:
        return self.qemu_command is not None and self.qemu_handle is None

    def start_instance(self) -> bool:
        if self.qemu_handle is not None:
            return False

        logger.debug(f"VM {self.instance.name}: Starting instance ...")
        try:
            self.qemu_handle = invoke_pexpect(self.qemu_command, needs_root=True)
            if self.debug:
                self.qemu_handle.logfile = sys.stdout
            self.qemu_handle.expect_exact("(qemu)", timeout=10)
        except pexpect.EOF as ex:
            raise Exception(f"Unable to start VM {self.instance.name}, process exited unexpected") from ex
        except pexpect.TIMEOUT as ex:
            raise Exception(f"Unable to start VM {self.instance.name}, timeout during QEMU start") from ex
        logger.info(f"VM {self.instance.name}: Instance was started!")
        return True

    def stop_instance(self) -> bool:
        if self.qemu_handle is None:
            return False

        logger.debug(f"VM {self.instance.name}: Stopping instance ...")
        try:
            self.qemu_handle.sendline("system_powerdown")
            self.qemu_handle.expect(pexpect.EOF, timeout=30)
        except pexpect.TIMEOUT as ex:
            raise Exception(f"Unable to stop VM {self.instance.name}, timeout occured:") from ex
        finally:
            self.qemu_handle = None

        logger.info(f"VM {self.instance.name}: Instance was stopped!")
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
            logger.opt(exception=ex).warning(f"VM {self.instance.name}: Unable to get status")
            return "VM status: unkown"
