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
        -nographic -serial mon:stdio 
        -kernel /tmp/isomount/install.amd/vmlinuz \
        -initrd /tmp/isomount/install.amd/initrd.gz \
        -enable-kvm -cpu host -no-reboot \
        -append "console=ttyS0,115200n8"
   ```
5. Unmount ISO
   ```bash
   umount /tmp/isomount
   ```
## TODO:

6. Prepare System
   1. Mount `<DISKIMAGE>` 
   2. Setup GRUB/Debian to use tty
   3. Copy Installation Package
   4. Unmount `<DISKIMAGE>`

7. Start VM and finish installation of the Base Image

