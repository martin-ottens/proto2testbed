from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from loguru import logger
from typing import List, Dict

import pexpect
import hashlib
import tempfile
import subprocess
import os
import sys
import time

class VMWrapper():
    __QEMU_NIC_TEMPLATE     = "-nic tap,model=e1000,ifname={tapname},mac={mac} "
    __QEMU_COMMAND_TEMPLATE = """qemu-system-x86_64 \
                                -boot c \
                                -m {memory} \
                                -enable-kvm \
                                -cpu host \
                                -smp {cores} \
                                -machine q35 \
                                -hda {image} \
                                {nics} \
                                -snapshot \
                                -cdrom {cloud_init_iso} \
                                -display none \
                                -monitor stdio"""
    __CLOUD_INIT_ISO_TEMPLATE = """genisoimage \
                                   -output {output} \
                                   -volid cidata \
                                   -joliet \
                                   -rock {input}"""

    @logger.catch(reraise=True)
    def __init__(self, name: str, management: Dict[str, str], 
                 extra_interfaces: List[str], image: str,
                 cores: int = 2, memory: int = 1024, debug: bool = False):
        
        self.name = name
        self.debug = debug
        self.qemu_handle = None

        if len(extra_interfaces) > 4:
            logger.error(f"VM {name}: Error during creation, 4 interfaces are allowed, but {len(extra_interfaces)} were added!")
            return

        if not all(key in management for key in ["interface", "ip", "gateway", "netmask"]):
            logger.error(f"VM {name}: Error during creation, management config is not correct!")
            return

        self.tempdir = tempfile.TemporaryDirectory()
 
        # Generate cloud-init files
        init_files = Path(self.tempdir.name) / "cloud-init"
        os.mkdir(init_files)

        j2_env = Environment(loader=FileSystemLoader("../vm_templates/"))

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
            mgmt_address=management["ip"],
            mgmt_server=management["gateway"],
            mgmt_netmask=management["netmask"]
        )
        with open(init_files / "network-config", mode="w", encoding="utf-8") as handle:
            handle.write(network_config)

        cloud_init_iso = str(Path(self.tempdir.name) / "cloud-init.iso")
        process = subprocess.run([VMWrapper.__CLOUD_INIT_ISO_TEMPLATE.format(input=init_files, output=cloud_init_iso)], 
                                 shell=True, 
                                 capture_output=True)
        
        if process.returncode != 0:
            logger.error(f"VM {self.name}: Unbale to run genisoimage: {process.stderr.decode('utf-8')}")
            sys.exit(1)
        
        # Generate pseudo unique interface macs
        hash_hex = hashlib.sha256(name.encode()).hexdigest()
        base_mac = hash_hex[1:2] + 'e:' + hash_hex[2:4] + ':' + hash_hex[4:6] + ':' + hash_hex[6:8] + ':' + hash_hex[8:10] + ':' + hash_hex[10:11]
        
        interfaces = VMWrapper.__QEMU_NIC_TEMPLATE.format(tapname=management["interface"], mac=(base_mac + "0"))
        for index, name in enumerate(extra_interfaces):
            interfaces += VMWrapper.__QEMU_NIC_TEMPLATE.format(tapname=name, mac=(base_mac + str(index + 1)))

        # Prepare qemu command
        self.qemu_command = VMWrapper.__QEMU_COMMAND_TEMPLATE.format(
            memory=memory,
            cores=cores,
            image=image,
            nics=interfaces,
            cloud_init_iso=cloud_init_iso
        )

    def __del__(self):
        if self.qemu_handle is not None:
            self.stop_instance()

        self.tempdir.cleanup()
        logger.debug(f"VM {self.name}: Destoryed and cleaned up.")

    def ready_to_start(self) -> bool:
        return self.qemu_command is not None and self.qemu_handle is None

    def start_instance(self) -> bool:
        if self.qemu_handle is not None:
            return False

        logger.debug(f"VM {self.name}: Starting instance ...")
        try:
            self.qemu_handle = pexpect.spawn(self.qemu_command, timeout=None, encoding="utf-8")
            if self.debug:
                self.qemu_handle.logfile = sys.stdout
            self.qemu_handle.expect_exact("(qemu)", timeout=10)
        except pexpect.EOF as ex:
            logger.opt(exception=ex).error(f"VM {self.name}: Unable to start, process exited unexpected:")
            return False
        except pexpect.TIMEOUT as ex:
            logger.opt(exception=ex).error(f"VM {self.name}: Unable to start, timeout during QEMU start:")
            return False
        logger.info(f"VM {self.name}: Instance was started!")
        return True

    def stop_instance(self) -> bool:
        logger.debug(f"VM {self.name}: Stopping instance ...")
        try:
            self.qemu_handle.sendline("system_powerdown")
            self.qemu_handle.expect(pexpect.EOF, timeout=30)
        except pexpect.TIMEOUT as ex:
            logger.opt(exception=ex).error(f"VM {self.name}: Unable to stop, timeout occured:")
            return False
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
            logger.opt(exception=ex).warning(f"VM {self.name}: Unable to get status:")
            return "VM status: unkown"

#if __name__ == "__main__":
#
#    # ip tuntap add dev vnet0 mode tap
#    # ip tuntap add dev vnet2 mode tap
#    # ip link set dev vnet0 master br0
#
#
#
#    qemu_instance = VMWrapper(
#        name="vma.test.system", 
#        management={"interface": "vnet0", "ip": "172.16.99.2", "gateway": "172.16.99.1", "netmask": "255.255.255.0"}, 
#        extra_interfaces=["vnet1"],
#        image="/root/debian.qcow"
#    )
#    qemu_instance.start_instance()
#    print(qemu_instance.instance_status())
#    time.sleep(20)
#    qemu_instance.stop_instance()
