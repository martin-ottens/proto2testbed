# Example 1: Routed WireGuard Example

## Overview

### What is this experiment doing?
Two client endpoints in two different subnets are connected via a router, this router will route traffic between the networks, so the client endpoints can reach each other. 30 seconds into the experiment the router will add an artificial delay of 100ms to one of its interfaces.

During the experiment an *iperf3* TCP test is running between both client endpoints and the ping is measured.

In the *normal* version, the endpoints are connected directly, all traffic is transmitted encrypted via the router. In the *wireguard* version, WireGuard is enabled on both client endpoints, creating an encrypted tunnel between. 

This setup allows seeing, how the throughput in both version is impacted when the delay between the endpoints suddenly increases.

Example results can be found at `results/example1_{normal,wireguard}`.

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
|     eth1     |    |    eth1    |    eth2    |    |     eth1     |
+--------------+    +------------+------------+    +--------------+
 #     ||                 ||           ||                 ||     #
 #     ||                 ||           ||                 ||     #
 #   ====== Bridge exp0 ======       ====== Bridge exp1 ======   #
 #                                                               #
 ### 192.168.0.1/24 #### WireGuard Tunnel ##### 192.168.0.2/24 ### 
```

## Guide

0. Create a base image as described in `/baseimage_creation/README.md`. Start a session as `root` user.

1. Build current version of Instance Manager:
   ```bash
   cd <proto-testbed>/instance-manager/
   make all
   ```

2. Prepare two VM Images:
    - Image for the router:
      ```bash
      cd <proto-testbed>/baseimage-creation
      ./im-installer.py -i <path/to/your/baseimage> -o /tmp/router.qcow2 -p ../instance-manager/instance-manager.deb
      ```
    - Image for the endpoints:
      ```bash
      ./im-installer.py -i <path/to/your/baseimage> -o /tmp/endpoints.qcow2 -p ../instance-manager/instance-manager.deb -e ../setups/example1/wireguard.extra
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
