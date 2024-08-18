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
from utils.system_commands import invoke_subprocess, invoke_pexpect, get_asset_relative_to

class VMWrapper(Dismantable):
    __QEMU_NIC_TEMPLATE     = "-nic tap,model={model},ifname={tapname},mac={mac} "
    __QEMU_COMMAND_TEMPLATE = """qemu-system-x86_64 \
                                -boot c \
                                -m {memory} \
                                {kvm} \
                                -smp {cores} \
                                -machine q35 \
                                -hda {image} \
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

    def __init__(self, name: str, management: Dict[str, str], 
                 extra_interfaces: List[str], image: str,
                 cores: int = 2, memory: int = 1024, debug: bool = False, 
                 disable_kvm: bool = False, netmodel: str = "virtio") -> None:
        self.name = name
        self.debug = debug
        self.qemu_handle = None

        if not all(key in management for key in ["interface", "ip", "gateway"]):
            raise Exception(f"Error during creation, management config is not correct!")

        self.ip_address = management["ip"].ip

        if len(extra_interfaces) > 4:
            raise Exception(f"Error during creation, 4 interfaces are allowed, but {len(extra_interfaces)} were added!")


        self.tempdir = tempfile.TemporaryDirectory()
 
            # Generate cloud-init files
        try:
            init_files = Path(self.tempdir.name) / "cloud-init"
            os.mkdir(init_files)

            j2_env = Environment(loader=FileSystemLoader(get_asset_relative_to(__file__, "../vm_templates/")))

            meta_data = j2_env.get_template("meta-data.j2").render()
            with open(init_files / "meta-data", mode="w", encoding="utf-8") as handle:
                handle.write(meta_data)

            domain_parts = name.split('.')
            fqdn = "\"\""
            if len(domain_parts) > 2:
                fqdn = "\"" + '.'.join(domain_parts[1:]) + "\""
            
            user_data = j2_env.get_template("user-data.j2").render(
                hostname=name,
                fqdn=fqdn
            )
            with open(init_files / "user-data", mode="w", encoding="utf-8") as handle:
                handle.write(user_data)

            network_config = j2_env.get_template("network-config.j2").render(
                mgmt_address=str(management["ip"].ip),
                mgmt_server=str(management["gateway"]),
                mgmt_netmask=management["ip"].with_prefixlen.split("/")[1]
            )
            with open(init_files / "network-config", mode="w", encoding="utf-8") as handle:
                handle.write(network_config)

            cloud_init_iso = str(Path(self.tempdir.name) / "cloud-init.iso")
            process = invoke_subprocess([VMWrapper.__CLOUD_INIT_ISO_TEMPLATE.format(input=init_files, output=cloud_init_iso)],
                                        shell=True)
            
            if process.returncode != 0:
                raise Exception(f"Unbale to run genisoimage: {process.stderr.decode('utf-8')}")
            
            # Generate pseudo unique interface macs
            hash_hex = hashlib.sha256(name.encode()).hexdigest()
            base_mac = hash_hex[1:2] + 'e:' + hash_hex[2:4] + ':' + hash_hex[4:6] + ':' + hash_hex[6:8] + ':' + hash_hex[8:10] + ':' + hash_hex[10:11]
            
            interfaces = VMWrapper.__QEMU_NIC_TEMPLATE.format(model=netmodel, tapname=management["interface"], mac=(base_mac + "0"))
            for index, name in enumerate(extra_interfaces):
                interfaces += VMWrapper.__QEMU_NIC_TEMPLATE.format(model=netmodel, tapname=name, mac=(base_mac + str(index + 1)))

            # Prepare qemu command
            self.qemu_command = VMWrapper.__QEMU_COMMAND_TEMPLATE.format(
                memory=memory,
                cores=cores,
                image=image,
                nics=interfaces,
                cloud_init_iso=cloud_init_iso,
                kvm=(VMWrapper.__QEMU_KVM_OPTIONS if not disable_kvm else '')
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

    def get_name(self) -> str:
        return f"VirtualMachine {self.name}"

    def ready_to_start(self) -> bool:
        return self.qemu_command is not None and self.qemu_handle is None

    def start_instance(self) -> bool:
        if self.qemu_handle is not None:
            return False

        logger.debug(f"VM {self.name}: Starting instance ...")
        try:
            self.qemu_handle = invoke_pexpect(self.qemu_command, needs_root=True)
            if self.debug:
                self.qemu_handle.logfile = sys.stdout
            self.qemu_handle.expect_exact("(qemu)", timeout=10)
        except pexpect.EOF as ex:
            raise Exception(f"Unable to start VM {self.name}, process exited unexpected") from ex
        except pexpect.TIMEOUT as ex:
            raise Exception(f"Unable to start VM {self.name}, timeout during QEMU start") from ex
        logger.info(f"VM {self.name}: Instance was started!")
        return True

    def stop_instance(self) -> bool:
        if self.qemu_handle is None:
            return False

        logger.debug(f"VM {self.name}: Stopping instance ...")
        try:
            self.qemu_handle.sendline("system_powerdown")
            self.qemu_handle.expect(pexpect.EOF, timeout=30)
        except pexpect.TIMEOUT as ex:
            raise Exception(f"Unable to stop VM {self.name}, timeout occured:") from ex
        finally:
            self.qemu_handle = None

        logger.info(f"VM {self.name}: Instance was stopped!")
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
            logger.opt(exception=ex).warning(f"VM {self.name}: Unable to get status")
            return "VM status: unkown"
