# Base-Image Creation

An OS installation with certain configurations and dependencies is required to execute a testbed. The basic installation of the operating system is usually only carried out once; the base-image created in the process can later be used to create testbed-specific images.

Debian 12 "Bookworm" is currently supported as the operating system, whereby it should be possible to easily migrate the installation process and configuration to other Debian-based systems.

## Template Base-Image Creation

### Fully automated Zero-Touch Base-Image Creation
The script `make-baseimage.sh` can create base-images with AMD64 Debian 12 "Bookworm" installations in a fully automated way:

1. Download an AMD64 Debian 12 ISO --> `<ISO>` (e.g., [Netinstall Image](https://www.debian.org/CD/netinst/))
2. Run the script:
   ```bash
   sudo make-baseimage.sh <ISO> </path/to/output-image.qcow2>
   ```
   Optionally, use the `--size` parameter to set a size for the disk image (defaults to `4G`)
3. After some minutes, the disk base-image was written to `</path/to/output-image.qcow2>`. 
   The created image can used with the `im-installer.py` script to install additional dependencies and make executable in a testbed.

### Manual Base-Image Creation via Serial Mode

1. Download a Debian 12 ISO --> `<ISO>` (e.g., [Netinstall Image](https://www.debian.org/CD/netinst/))
2. Prepare Disk Image
   ```bash
   qemu-img create -f qcow2 <DISKIMAGE>.qcow2 4G
   ```
3. Mount ISO to local filesystem
   ```bash
   sudo mkdir -p /tmp/isomount
   sudo mount -r -o loop <ISO> /tmp/isomount
   ```
4. Start QEMU with Serial monitor & launch Debian with forced serial installer
   ```bash
   sudo qemu-system-x86_64 -m 1G -hda <DISKIMAGE>.qcow2 \
        -cdrom <ISO> -boot d \
        -nographic -serial mon:stdio \
        -kernel /tmp/isomount/install.amd/vmlinuz \
        -initrd /tmp/isomount/install.amd/initrd.gz \
        -enable-kvm -cpu host -no-reboot \
        -append "console=ttyS0,115200n8"
   ```
   To allow zero-touch image preparation by the `im-installer.py` script, it
   is required to use the following configuration in the installer:
   - **Locale:** `en_US.UTF-8`
   - **Keyboard Layout**: English
   - **Hostname:** `debian`
   - **Root Password:** `1`
   - **Additional User:** `testbed`, Password `1`

   Omit the options `-enable-kvm -cpu host` when running `qemu-system-x86_64` on a virtual machine without nested KVM.
5. Unmount ISO
   ```bash
   sudo umount /tmp/isomount
   ```
6. The created image can used with the `im-installer.py` script to install additional dependencies and make executable in a testbed.

## Installation of the Instance Manager and Additional Dependencies
Before the base-image created in the steps above can be used in a testbed run, the Instance Manager has to be installed. The Instance Manager handles the communication with the testbed controller, installs additional experiments and applies some configuration changes to the image. During the installation of the Instance Manager, users could install additional common dependencies to create a experiment-specific base-image where, e.g. kernel modules that do not change between testbed runs, are installed. 

**Please note:** After the `instance-manager.deb` package is installed, the image is finalized and can (due to optimizations) no longer be used with the `im-installer.py` script to install additional dependencies.

### Fully automated installation of the Instance Manager

1. Build the Instance Manager Debian package `instance`:
   ```bash
   cd <path/to/proto-tetsbed>/instance-manager
   make all
   ```
2. Run the `im-installer.py` script:
   ```bash
   sudo ./im-installer.py -i <path/to/input/image.qcow2> -o <path/to/output/image.qcow2> -p <path/to/proto-testbed>/instance-manager/instance-manager.deb
   ```
   If `-i <input>` and `-o <output>` are provided, the image given in `<input>` is copied to `<output>` prior to modification. If `<output>` is omitted, the image `<input>` is modified in place.
   The following additional options are available:
   - `-e <extra commands>`: List of extra commands that are executed after the Instance Manager is installed. Note, that all commands need to run non-interactive. The file should be provided in the following format:
     ```
     apt-get -y install my-dependency
     touch /etc/my-dependecy/installed
     ```
   - `-m <directory>`: Mount a local direcotry with additional dependencies or packages to `/mnt/additional`. Can be used together with the extra command flag to install custom packages, e.g.:
     ```
     apt-get -y install /mnt/additional/my-package.deb
     ```
   - `--debug`: Show serial terminal during installation (non-interactive)
   - `--timeout <seconds>`: Set timeout for all commands (defaults to `60`)
3. The image at the path `<output>` (or `<input>` if modified in place) can now the used in a testbed.

### Manually Install the Instance Manager

**Please note:** This can also be handeled automatically by the `im-installer.py` script if the installation was configured as mentioned above. This section is intended for base-images that are configured in a different way during installation (e.g., use of another OS) and the `im-installer.py` script is not applicable.

1. Build the Instance Manager Debian package `instance`:
   ```bash
   cd <path/to/proto-tetsbed>/instance-manager
   make all
   ```
2. Start QEMU normally
   ```bash
   sudo qemu-system-x86_64 -m 1G -hda <DISKIMAGE>.qcow2 \
        -enable-kvm -cpu host -boot c \
        -nographic -serial mon:stdio \
        -virtfs local,path=<PATH TO DIRECTORY with instance-manager.deb>,mount_tag=host0,security_model=passthrough,id=host0
   ```
   Omit the options `-enable-kvm -cpu host` when running `qemu-system-x86_64` on a virtual machine without nested KVM.
3. The serial console of the system attaches, login as root
4. On the machine, install all requirements:
   ```bash
   mount -t 9p -o trans=virtio host0 /mnt
   apt-get install -y /mnt/instance-manager.deb
   # Do your individual setup stuff
   ```
5. Shut down the machine, the image is ready.
   ```bash
   shutdown now
   ```
