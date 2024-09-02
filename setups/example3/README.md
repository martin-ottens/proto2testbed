# Example 3: Real Hardware

## Overview

### What is this experiment doing?
The testbed is subdivided in two area, each area consists of a network bridge, two Instances and a subnet. Each of the network bridges is connected to a physical port of the testbed host.

Between these pyhsical ports (and therefore both subnets) a hardware router is routing, in our testcase another Linux machine is used.

During the experiments, Integrations will switch the port speed of eno2 and eno3 to 100Mbit/s without auto-negotiation to test how the router reacts to such scenarios, and what kind of implication its reaction to the Applications has.

This example show the possibility to integrate real hardware to a testbed and use the testbed system to conduct real end-to-end tests with application workloads over physical hardware. 

### Schematic testbed overview
```
+---------------+                                        +---------------+
|  a1-endpoint  |      +---------------------------+     |  b1-endpoint  |
|               |      |      HARDWARE ROUTER      |     |               |
| Apps:         |      |        10.0.1.1/24        |     | Apps:         |
| iperf-server  |      |        10.0.2.1/24        |     | iperf-client  |
|               |      +---------------------------+     | ping          |
|  10.0.1.2/24  |        ||                    ||        |  10.0.2.2/24  |
+---------------+        ||                    ||        +---------------+
|    enp0s3     |====\\  OO eno2          eno3 OO  //====|    enp0s3     |
+---------------+    ||  ||                    ||  ||    +---------------+
+---------------+    ||  ||      Physical      ||  ||    +---------------+
|  a2-endpoint  |    ||  ||       Ports        ||  ||    |  b2-endpoint  |
|               |  +--------+                +--------+  |               |
| Apps:         |  | Bridge |                | Bridge |  | Apps:         |
| iperf-server  |  | exp0   |                | exp1   |  | iperf-client  |
| ping          |  +--------+                +--------+  |               |
|  10.0.1.3/24  |    ||                            ||    |  10.0.2.3/24  |
+---------------+    ||                            ||    +---------------+
|    enp0s3     |====//                            \\====|    enp0s3     |
+---------------+                                        +---------------+
```

## Guide

**Please Note:** It is assumed, that `eno2` and `eno3` are the pysical interfaces of the Testbed Hosts for this experiment. If the names differ in your setup, change the interfaces in `testbed.json` accordingly.

1. Build current version of Instance Manager:
   ```bash
   cd <proto-testbed>/instance-manager/
   make all
   ```

2. Prepare the VM image:
    ```bash
    cp path/to/your/baseimage.qcow2 /tmp/endpoint.qcow2
    cd <proto-testbed>/scripts/
    ./image_creator.py /tmp/endpoint.qcow2 ../instance-manager/instance-manager.deb
    ```

3. Install ethtool on the Testbed Host
   ```bash
    apt install -y ethtool
   ```

3. Load required environment variables:
    ```bash
    export EXPERIMENT_TAG=hardware_test
    export INFLUXDB_DATABASE=testbed
    ```

4. Start the testbed:
   ```bash
   cd proto-testbed
   ./proto-testbed -e $EXPERIMENT_TAG setups/example3
   ```

5. Export the results (and clean up):
   ```bash
   cd <proto-testbed>/scripts/
   ./result_renderer.py --config ../setups/example3/testbed.json --influx_database $INFLUXDB_DATABASE --experiment $EXPERIMENT_TAG --renderout ./${EXPERIMENT_TAG}-images

   ./result_export.py --config ../setups/example3/testbed.json --influx_database $INFLUXDB_DATABASE --experiment $EXPERIMENT_TAG --output ./${EXPERIMENT_TAG}-csvs

    # Optional: Clean up data from InfluxDB (Should be done before repeating the experiment)
    ./result_cleanup.py --experiment $EXPERIMENT_TAG --influx_database $INFLUXDB_DATABASE

    # Optional: Delete disk images (After all experiments are completed)
    rm /tmp/endpoint.qcow2
   ```

## Setup a Linux host as router
The host has the interfaces `eno2` (connected to `eno2` of the Testbed Host) and `eno3` (connected to `eno3` of the Testbed Host):
```bash
sudo -s
sysctl -w net.ipv4.ip_forward=1
iptables --policy FORWARD ACCEPT

ip address add 10.0.1.1/24 dev eno2
ip address add 10.0.2.1/24 dev eno3

ip link set up dev eno2
ip link set up dev eno3
```
