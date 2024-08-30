# Example 2: Emulation Setup

## Overview

### What is this experiment doing?
Two client endpoints in two different subnets are connected via ns-3. The ns-3 simulator is running in RealTime mode, so together with Proto-Testbed, a emulation setup is provided.

The ns-3 simulation process provides 1 or 10 virtual router, that sits between the client endpoints and allow the entpoints to commincate.

During the experiment the TCP throughput is measured using iperf3. Also stats about the ICMP ping are collected.

This experimets allow to get an overview what performance implications (simple) simulated topologies has for the emulation setup. 

### Schematic testbed overview
```
N = Number of router \in {1,10}

+---------------+    +----------------------------------------------------------+    +---------------+
|  endpoint-a   |    | ns-3 Simulation Process running on the Testbed Host      |    |  endpoint-b   |
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

1. Build current version of Instance Manager:
   ```bash
   cd <proto-testbed>/instance-manager/
   make all
   ```

2. Prepare the VM image:
    ```bash
    cp path/to/your/baseimage.qcow2 /tmp/router.qcow2
    cd <proto-testbed>/scripts/
    ./image_creator.py /tmp/router.qcow2 ../instance-manager/instance-manager.deb
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

    # In every case: Set the name of the InfluxDB database
    export INFLUXDB_DATABASE=testbed
    ```

4. Start the testbed:
   ```bash
   cd proto-testbed
   ./proto-testbed -e $EXPERIMENT_TAG setups/example2
   ```

5. Export the results (and clean up):
   ```bash
   cd <proto-testbed>/scripts/
   ./result_renderer.py --config ../setups/example2/testbed.json --influx_database $INFLUXDB_DATABASE --experiment $EXPERIMENT_TAG --renderout ./${EXPERIMENT_TAG}-images

   ./result_export.py --config ../setups/example2/testbed.json --influx_database $INFLUXDB_DATABASE --experiment $EXPERIMENT_TAG --output ./${EXPERIMENT_TAG}-csvs

    # Optional: Clean up data from InfluxDB (Should be done before repeating the experiment)
    ./result_cleanup.py --experiment $EXPERIMENT_TAG --influx_database $INFLUXDB_DATABASE

    # Optional: Delete disk images (After all experiments are completed)
    rm /tmp/endpoint.qcow2
   ```
