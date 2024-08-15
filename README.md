# Proto-Testbed

## 1. Prepare Host Machine

Install a current Debian 12 OS, no GUI is required. All following commands and
the actual testbed experiments are run with the `root` User (`sudo -s` or `su`).

Clone this repository to any desired location on the host. All paths in this
README are relative to the root of the cloned repo.

### Installation of Required Dependencies on Host
```bash
apt install qemu-utils qemu-system-x86 qemu-system-gui bidge-utils iptables net-tools genisoimage python3 iproute2 influxdb influxdb-client make
```

The InfluxDB is by default configured to allow arbitrary, privileged connections (the management network of the testbed needs full access to the InfluxDB on the host).
It is only required to create a database for the testbed (name can be arbitrary, `testbed` in this case):
```bash
influx -execute 'CREATE DATABASE testbed'
```

### Python Dependencies
#### System-Wide-Debian Packages (Recommended)
```bash
apt install python3-jinja2 python3-pexpect python3-loguru python3-jsonschema python3-influxdb python3-psutil
```

Additional Debian packages for plot rendering:
```bash
apt install python3-numpy python3-matplotlib
```

#### Virtual Environment
```bash
apt install python3-virtualenv python3-pip
virtualenv -p python3 venv
source venv/bin/activate
pip install -r requirements.txt
```

## 2. Prepare an Image

### Create Debian Package
Download the latest `instance-manager.deb` from the CI or build it yourself on
the host machine:
```bash
cd instance-manager
make all
```

### Create an Image
Create a Debian image as described in `IMAGE_CREATION.md`, an image with the
basic installation already completed can be downloaded [here](https://cloud.martin-ot.de/s/gDEtxtCAGbwFYwz).

### Install Dependencies in Image
Prepare the image by installing the required dependencies and the `instance-manager.deb` package. You can do this manually (as described in `IMAGE_CREATION.md`) or use the zero-touch script:
```bash
cd scripts
./image_creator.py <IMAGE.qcow2> ../instance-manager/instance-manager.deb
```
It is recommended to copy the base image before running this step, so that you
can start over again with a fresh base image whenever changes to the image or the
instance-manager are needed.

When creating the image on a virtual machine itself, you can pass `--no_kvm` to `image_creater.py`.

## 3. Run an Example

**Remember:** Only one testbed can be executed on the host at any given time!

### Start the experiment
Before starting: Change the image path for all testbed machines (in this repo: `"diskimage": "/root/debian-test.qcow2"`) in `setups/sample/testbed.json` to the correct path of the image created in the previous step.

```bash
export INFLUXDB_DATABASE=testbed
./proto-testbed -e exmaple ../setups/sample
```
The following options are helpful (see `./proto-testbed -h` for further details):
- **`-d`**: Do not store any results to InfluxDB (useful for debugging)
- **`--clean`**: Cleanup previous, not fully dismantled testbed setups network modifications
- **`--pause INIT`**: Halt the testbed after VM initialization and do not run experiments (useful for debugging, e.g. SSH into VMs)

Running the testbed system on a virtual machine itself is possible, but not recommended for productive use due to severe speed penalties. To allow this testing purposes, add `--no_kvm` when starting an experiment. (Other options, not documented here: Enable nested KVM virtualization in the host systems kernel.)

### Plot and/or Export data
```bash
cd scripts
./result_renderer.py --config ../setups/sample/testbed.json --experiment example --influx_database testbed --renderout ./plots # Render matplotlib plots to ./plots
./result_export.py -config ../setups/sample/testbed.json --experiment example --influx_database testbed --output ./csvs # Export experiment data as CSV to ./csvs
```

### Clean up
```bash
cd scripts
./result_cleanup.py --experiment example --influx_database testbed
```

## 4. Optional: Use Host for GitLab-CI-Integration

> **Notice:** The Runner will be run as root. Depending on configuration of the repo and pipeline, all persons with access to the GitLab repo will have full root control over the testbed host by design. 

1. Install GitLab-Runner as described [here](https://docs.gitlab.com/runner/install/linux-repository.html).
2. Register the GitLab Runner as a shell runner for the project. Per default, `concurrent` is set to `1`. Since it is not possible to run concurrent testbed on a host, ensure this setting is not changed (see `/etc/gitlab-runner/config.toml`)
3. Start the GitLab-Runner as `root` user by changing `"--user" "gitlab-runner"` to `"--user" "root"` in `/etc/systemd/system/gitlab-runner.service`. Restart the runner:
    ```bash
    systemctl daemon-reload
    systemctl restart gitlab-runner.service
    ```
3. Add testbed scripts to system path, easy but hacky way:
    ```bash
    cd /usr/local/bin
    ln -s <REPO_BASE>/proto-testbed .
    ln -s <REPO_BASE>/scripts/* .
    ```

## Background functions / Inner Workings

### Creation of Management Network, attach VM TAPs
```bash
brctl addbr br-mgmt
ip addr add 172.16.99.1/24 dev br-mgmt
ip link set up dev br-mgmt
# Start VM instances [...]
brctl addif br-mgmt vma-mgmt
brctl addif br-mgmt vmb-mgmt

# Test
ping 172.16.99.2 && ssh user@172.16.99.2
```

### Experiment Network
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

### Enable NATted Internet Access for Management Network
```bash
sysctl -w net.ipv4.conf.all.forwarding=1
iptables -A FORWARD -s 172.16.99.0/24 -j ACCEPT
iptables -A FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables -t nat -A POSTROUTING -s 172.16.99.0/24 -j SNAT --to-source 10.2.30.20
```
