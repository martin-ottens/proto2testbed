# Example 1: Routed WireGuard Example

## Overview

### What is this experiment doing?
Two client endpoints in two different subnets are connected via a router, this router will route traffic between the networks, so the client endpoints can reach each other. 30 seconds into the experiment the router will add an artificial delay of 100ms to one of its interfaces.

During the experiment an *iperf3* TCP test is running between both client enpoints and the ping is measured.

In the *normal* version, the endpoints are conncted directly, all traffic is transmitted enencrypted via the router. In the *wireguard* version, WireGuard is enabled on both client endpoints, creating a encrypted tunnel between. 

This setup allows to see, how the throughput in both version is impacted when the delay between the endpoints suddenly increases.

### Schematic testbed overview
```
+--------------+    +-------------------------+    +--------------+
|  a-endpoint  |    |         router          |    |  b-endpoint  |
|              |    |                         |    |              |
| Apps:        |    | Apps:                   |    | Apps:        |
| iperf-server |    | 100ms delay after 30s   |    | iperf-client |
|              |    |                         |    | ping         |
|  10.0.1.1/24 |    | 10.0.1.2/24 10.0.2.2/24 |    | 10.0.2.1/24  |
+--------------+    +------------+------------+    +--------------+
|    enp0s3    |    |   enp0s3   |   enp0s4   |    |    enp0s3    |
+--------------+    +------------+------------+    +--------------+
 #     ||                 ||           ||                 ||     #
 #     ||                 ||           ||                 ||     #
 #   ====== Bridge exp0 ======       ====== Bridge exp1 ======   #
 #                                                               #
 ### 192.168.0.1/24 #### WireGuard Tunnel ##### 192.168.0.2/24 ### 
```

## Guide

1. Build current version of Instance Manager:
   ```bash
   cd proto-testbed/instance-manager/
   make all
   ```

2. Prepare two VM Images:
    - Image for the router:
      ```bash
      cp path/to/your/baseimage.qcow2 /tmp/router.qcow2
      cd <proto-testbed>/scripts/
      ./image_creator.py /tmp/router.qcow2 ../instance-manager/instance-manager.deb
      ```
    - Image for the endpoints:
      ```bash
      cp path/to/your/baseimage.qcow2 /tmp/endpoint.qcow2
      cd <proto-testbed>/scripts/
      ./image_creator.py --extra ../setups/example1/wireguard.extra /tmp/endpoint.qcow2 ../instance-manager/instance-manager.deb
      ```

3. Load required environment variables:
    ```bash
    cd <proto-testbed>/setup/example1
    # For experiment without WireGuard enabled
    export $(grep -v '^#' .env-normal | xargs)
    # For experiment with WireGuard enabled
    export $(grep -v '^#' .env-wireguard | xargs)
    ```

4. Start the testbed:
   ```bash
   cd <proto-testbed>
   ./proto-testbed run -e $EXPERIMENT_TAG setups/example1
   ```

5. Export the results (and clean up):
   ```bash
   ./proto-testbed export -e $EXPERIMENT_TAG -o ./${EXPERIMENT_TAG}-images image setups/example1
   ./proto-testbed export -e $EXPERIMENT_TAG -o ./${EXPERIMENT_TAG}-csvs csv setups/example1 

    # Optional: Clean up data from InfluxDB (Should be done before repeating the experiment)
   ./proto-testbed clean -e $EXPERIMENT_TAG

    # Optional: Delete disk images (After all experiments are completed)
    rm /tmp/{router,endpoint}.qcow2

   ```
