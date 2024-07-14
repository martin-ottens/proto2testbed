# Proto-Testbed

## Installation of required Dependencies on Host
```bash
apt install qemu-utils qemu-system-x86 qemu-system-gui bidge-utils iptables net-tools genisoimage
```

## Image Creation
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

## Management Network
- VMs Management Interface: `172.16.99.0/24`
- Host Management Interface: `172.16.99.1/24`
- Host Public Address: `10.2.30.20/24`

Example Wrapper Code:
```python
vma = VMWrapper(
    name="vma.test.system", 
    management_interface="vma-mgmt", 
    experiment_interface="vma-exp", 
    management_ip="172.16.99.2", 
    management_server="172.16.99.1", 
    image="/root/image.qcow2"
)
vmb = VMWrapper(
    name="vmb.test.system", 
    management_interface="vmb-mgmt", 
    experiment_interface="vmb-exp", 
    management_ip="172.16.99.3", 
    management_server="172.16.99.1", 
    image="/root/image.qcow2"
)
vma.start_instance()
vmb.start_instance()
time.sleep(600 * 10)
vma.stop_instance()
vmb.stop_instance()
```

```bash
brctl addbr br-mgmt
ip addr add 172.16.99.1/24 dev br-mgmt
ip link set up dev br-mgmt
# Start VM instances [...]
brctl addif br-mgmt vma-mgmt
brctl addif br-mgmt vmb-mgmt
ping 172.16.99.2 && ssh user@172.16.99.2
```

Optional/Additonal: Setup simple Experiment network via Virtual Switch 
```bash
brctl addbr br-exp
brctl addif br-exp vma-exp
brctl addif br-exp vmb-exp
ip link set up dev br-exp
# On vma:
vma$ sudo ip addr add 10.0.0.2/24 dev enp0s3
vma$ sudo ip link set up dev enp0s3
# On vmb:
vmb$ sudo ip addr add 10.0.0.3/24 dev enp0s3
vmb$ sudo ip link set up dev enp0s3
vmb$ ping 10.0.0.2
```

> **Notice:** When a bridge-device with a default route exists on the host,
> QEMU will attach the tap-devices to that bridge automatically 
> (see `/etc/qemu-ifup`).

Enable NATted Internet Access for Management Network:
```bash
sysctl -w net.ipv4.conf.all.forwarding=1
iptables -A FORWARD -s 172.16.99.0/24 -j ACCEPT
iptables -A FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables -t nat -A POSTROUTING -s 172.16.99.0/24 -j SNAT --to-source 10.2.30.20
```
