# Headless Debian Base Image Creation

1. Download Debian ISO -> `<ISO>`
2. Prepare Disk Image
   ```bash
   qemu-img create -f qcow2 <DISKIMAGE>.qcow2 10G
   ```
3. Mount ISO to local filesystem
   ```bash
   mkdir -p /tmp/isomount
   mount -r -o loop <ISO> /tmp/isomount
   ```
4. Start QEMU with Serial monitor & launch Debian with forced Serial installer
   ```bash
   qemu-system-x86_64 -m 1G -hda <DISKIMAGE>.qcow2 \
        -cdrom <ISO> -boot d \
        -nographic -serial mon:stdio \
        -kernel /tmp/isomount/install.amd/vmlinuz \
        -initrd /tmp/isomount/install.amd/initrd.gz \
        -enable-kvm -cpu host -no-reboot \
        -append "console=ttyS0,115200n8"
   ```
5. Unmount ISO
   ```bash
   umount /tmp/isomount
   ```
6. Start QEMU normally
   ```bash
   qemu-system-x86_64 -m 1G -hda <DISKIMAGE>.qcow2 \
        -enable-kvm -boot c \
        -nographic -serial mon:stdio \
        -virtfs local,path=<PATH TO instance-manager.deb>,mount_tag=host0,security_model=passthrough,id=host0
   ```
7. The serial console of the system attaches, login as root
8. On the machine, install all requirements:
   ```bash
   mount -t 9p -o trans=virtio host0 /mnt
   apt install /mnt/instance-manager.deb
   # Do your individual setup stuff
   ```
9. Shut down the machine, the image is ready.
   ```bash
   shutdown now
   ```
