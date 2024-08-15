# Image Creation

## Image Creation via Serial Mode
### Headless Debian Base Image Creation

1. Download Debian 12 ISO -> `<ISO>`
2. Prepare Disk Image
   ```bash
   qemu-img create -f qcow2 <DISKIMAGE>.qcow2 4G
   ```
3. Mount ISO to local filesystem
   ```bash
   mkdir -p /tmp/isomount
   mount -r -o loop <ISO> /tmp/isomount
   ```
4. Start QEMU with Serial monitor & launch Debian with forced serial installer
   ```bash
   qemu-system-x86_64 -m 1G -hda <DISKIMAGE>.qcow2 \
        -cdrom <ISO> -boot d \
        -nographic -serial mon:stdio \
        -kernel /tmp/isomount/install.amd/vmlinuz \
        -initrd /tmp/isomount/install.amd/initrd.gz \
        -enable-kvm -cpu host -no-reboot \
        -append "console=ttyS0,115200n8"
   ```
   To allow zero-touch image preparation by the `image_creater.py` script, it
   is required to use the following configuration in the installer:
   - **Locale:** `en_US.UTF-8`
   - **Keyboard Layout**: German
   - **Hostname:** `debian`
   - **Root Password:** `1`
   - **Additional User:** `testbed`, Password `1`

   Omit the options `-enable-kvm -cpu host` when running `qemu-system-x86_64` on a virtual machine.

5. Unmount ISO
   ```bash
   umount /tmp/isomount
   ```

### Install Instance Manager and Additional Parts
1. Start QEMU normally
   ```bash
   qemu-system-x86_64 -m 1G -hda <DISKIMAGE>.qcow2 \
        -enable-kvm -cpu host -boot c \
        -nographic -serial mon:stdio \
        -virtfs local,path=<PATH TO DIRECTORY with instance-manager.deb>,mount_tag=host0,security_model=passthrough,id=host0
   ```
   Omit the options `-enable-kvm -cpu host` when running `qemu-system-x86_64` on a virtual machine.
2. The serial console of the system attaches, login as root
3. On the machine, install all requirements:
   ```bash
   mount -t 9p -o trans=virtio host0 /mnt
   apt-get install -y /mnt/instance-manager.deb
   # Do your individual setup stuff
   ```
9. Shut down the machine, the image is ready.
   ```bash
   shutdown now
   ```

## Additional Installation Options
### Basic / Graphical Base Image Creation

Connect to the Host with SSH X-Forwarding.

```bash
qemu-img create -f qcow2 image.qcow2 4G
wget https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-12.6.0-amd64-netinst.iso
qemu-system-x86_64 -hda image.qcow2 -cdrom debian-12.6.0-amd64-netinst.iso -boot d -m 1024 -enable-kvm
# Optional: add -nographic -vnc :0 to enable VNC access to the VM
```

Install the OS, on the VM do at least the following steps as root:
```bash
# Do your idividual VM setup stuff [...]
echo "nameserver 1.1.1.1" > /etc/resolv.conf
apt install cloud-init
sed -i 's/GRUB_TIMEOUT=5/GRUB_TIMEOUT=0/' /etc/default/grub
update-grub2
shutdown now
```
Remember: `instance-manager.deb` is not installed, so no initialization or setup
is possible in the testbed system, the machine is only started by the testbed
controller with this setup.
