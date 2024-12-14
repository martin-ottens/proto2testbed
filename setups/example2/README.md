# Example 2: Emulation Setup

## Overview

### What is this experiment doing?
Two client endpoints in two different subnets are connected via ns-3. The ns-3 simulator is running in RealTime mode, so together with Proto-Testbed, an emulation setup is provided.

The ns-3 simulation process provides 1 or 10 virtual routers, that sits between the client endpoints and allow the endpoints to communicate. The simulated routers are connected with 1000Mbit/s CSMA/CD / Ethernet link.

During the experiment the TCP throughput is measured using iperf3. Also, stats about the ICMP pings are collected.

These experiments allow to get an overview what performance implications (simple) simulated topologies has for the emulation setup.

Example results can be found at `results/example2_{1router,10router}`.

### Schematic testbed overview
```
N = Number of router \in {1,10}

+---------------+    +----------------------------------------------------------+    +---------------+
|  a-endpoint   |    | ns-3 Simulation Process running on the Testbed Host      |    |  b-endpoint   |
|               |    |                  172.20.0.1    172.20.N.1                |    |               |
| Apps:         |    |  +----------+         +----------+         +----------+  |    | Apps:         |
| iperf-server  |    |  | Tap      | CSMA/CD | Router 1 | CSMA/CD | Tap      |  |    | iperf-client  |
|               |    |  | Endpoint |=========|    1..10 |=========| Endpoint |  |    | ping          |
| 172.20.0.2/24 |    |  |          |         +----------+         |          |  |    | 172.20.N.2/24 |
+---------------+    +-- TAP-BRIDGE --+                        +-- TAP-BRIDGE --+    +---------------+
|    enp0s3     |    |    ns3_em0     |                        |    ns3_em1     |    |    enp0s3     |
+---------------+    +----------------+------------------------+----------------+    +---------------+
       ||                   ||                                        ||                    ||
       ||                   ||                                        ||                    ||
     ======= Bridge exp0 =======                                    ======= Bridge exp1 =======
```

## Guide

0. Create a base image as described in `/baseimage_creation/README.md`. Start a session as `root` user.


1. Build current version of Instance Manager:
   ```bash
   cd <proto-testbed>/instance-manager/
   make all
   ```

2. Prepare the VM image (if the Instance Manager was not installed before):
    ```bash
    cd <proto-testbed>/baseimage-creation
    ./im-installer.py -i <path/to/your/baseimage> -o /tmp/endpoint.qcow2 -p ../instance-manager/instance-manager.deb
    ```

3. Prepare ns3 simulator
   ```bash
   cd /tmp
   git clone https://gitlab.com/nsnam/ns-3-dev.git
   cd ns-3-dev
   git checkout ns-3.41
   cp <proto-testbed>/setups/example2/ns-3/emulator.cc /tmp/scratch/.
   ./ns3 configure --disable-sudp
   ./ns build
   git apply <proto-testbed>/setups/example/ns-3/run-as-root.patch
   ```

3. Load required environment variables:
    ```bash
    cd <proto-testbed>/setup/example2
    # 1 router between the endpoints
    export $(grep -v '^#' .env-1router | xargs)
    # 10 routers between the endpoints
    export $(grep -v '^#' .env-10router | xargs)
    ```

4. Start the testbed:
   ```bash
   cd proto-testbed
   ./proto-testbed -e $EXPERIMENT_TAG setups/example2
   ```

5. Export the results (and clean up):
   ```bash
   ./proto-testbed export -e $EXPERIMENT_TAG -o ./${EXPERIMENT_TAG}-images image setups/example2
   ./proto-testbed export -e $EXPERIMENT_TAG -o ./${EXPERIMENT_TAG}-csvs csv setups/example2 

    # Optional: Clean up data from InfluxDB (Should be done before repeating the experiment)
   ./proto-testbed clean -e $EXPERIMENT_TAG

    # Optional: Delete disk images (After all experiments are completed)
    rm /tmp/endpoint.qcow2
   ```
