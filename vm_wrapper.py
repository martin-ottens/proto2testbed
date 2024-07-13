#!/usr/bin/python3

from pathlib import Path
from jinja2 import Environment, FileSystemLoader

import pexpect
import hashlib
import tempfile
import subprocess
import os
import sys
import time

class VMWrapper():
    __QEMU_COMMAND_TEMPLATE = """qemu-system-x86_64 \
                             -boot c \
                             -m {memory} \
                             -enable-kvm \
                             -cpu host \
                             -smp {cores} \
                             -machine q35 \
                             -hda {image} \
                             -nic tap,model=e1000,ifname={man_if},mac={man_mac} \
                             -nic tap,model=e1000,ifname={exp_if},mac={exp_mac} \
                             -snapshot \
                             -cdrom {cloud_init_iso} \
                             -display none \
                             -monitor stdio"""

    __CLOUD_INIT_ISO_TEMPLATE = """genisoimage \
                                   -output {output} \
                                   -volid cidata \
                                   -joliet \
                                   -rock {input}"""

    def __init__(self, name: str, management_interface: str, 
                 experiment_interface: str, management_ip: str, 
                 management_server: str, image: str,
                 cores: int = 2, memory: int = 1024):

        self.tempdir = tempfile.TemporaryDirectory()
 
        # Generate cloud-init files
        init_files = Path(self.tempdir.name) / "cloud-init"
        os.mkdir(init_files)

        j2_env = Environment(loader=FileSystemLoader("vm_templates/"))

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
            mgmt_address=management_ip,
            mgmt_server=management_server
        )
        with open(init_files / "network-config", mode="w", encoding="utf-8") as handle:
            handle.write(network_config)

        cloud_init_iso = str(Path(self.tempdir.name) / "cloud-init.iso")
        process = subprocess.run([VMWrapper.__CLOUD_INIT_ISO_TEMPLATE.format(input=init_files, output=cloud_init_iso)], 
                                 shell=True, 
                                 capture_output=True)
        
        if process.returncode != 0:
            print(f"Genisoimage failed: {process.stderr.decode('utf-8')}")
            sys.exit(1)
        
        # Generate pseudo unique interface macs
        hash_hex = hashlib.sha256(name.encode()).hexdigest()
        base_mac = hash_hex[1:2] + 'e:' + hash_hex[2:4] + ':' + hash_hex[4:6] + ':' + hash_hex[6:8] + ':' + hash_hex[8:10] + ':' + hash_hex[10:11]
        self.mgmt_mac = base_mac + '1'
        self.exp_mac  = base_mac + '2'

        # Prepare qemu command
        self.qemu_command = VMWrapper.__QEMU_COMMAND_TEMPLATE.format(
            memory=memory,
            cores=cores,
            image=image,
            man_if=management_interface,
            exp_if=experiment_interface,
            man_mac=self.mgmt_mac,
            exp_mac=self.exp_mac,
            cloud_init_iso=cloud_init_iso
        )

        self.qemu_handle = None

    def __del__(self):
        if self.qemu_handle is not None:
            self.stop_instance()

        self.tempdir.cleanup()

    def start_instance(self) -> bool:
        if self.qemu_handle is not None:
            return False

        self.qemu_handle = pexpect.spawn(self.qemu_command, timeout=None, encoding="utf-8")
        #self.qemu_handle.logfile = sys.stdout
        self.qemu_handle.expect_exact("(qemu)", timeout=10)
        return True

    def stop_instance(self) -> bool:
        self.qemu_handle.sendline("system_powerdown")
        self.qemu_handle.expect(pexpect.EOF, timeout=30)
        self.qemu_handle = None
        return True

    def instance_status(self) -> str:
        if self.qemu_handle is None:
            return "VM satus: inactive"
        
        self.qemu_handle.sendline("info status")
        self.qemu_handle.readline()
        status = self.qemu_handle.readline().strip()
        self.qemu_handle.expect_exact("(qemu)", timeout=1)
        return status

if __name__ == "__main__":

    # ip tuntap add dev vnet0 mode tap
    # ip tuntap add dev vnet2 mode tap
    # ip link set dev vnet0 master br0

    qemu_instance = VMWrapper(
        name="vma.test.system", 
        management_interface="vnet0", 
        experiment_interface="vnet2", 
        management_ip="10.2.30.23", 
        management_server="10.2.30.1", 
        image="/root/debian.qcow"
    )
    qemu_instance.start_instance()
    print(qemu_instance.instance_status())
    time.sleep(600)
    qemu_instance.stop_instance()
