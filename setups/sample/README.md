# Framework Test Example

## Overview
This example is intended to test and demonstrate various features of Proto²Testbed.
It is configured to do the following things:
- Two instances (`vma`, `vmb`) are created and connected via one network (`exp0`). The instances are set up with the scripts `{vma,vmb}/setup.sh`.
- During the experiment, different bundled applications are executed on the Instances. On Instance `vma` an application is dynamically loaded from `apps/log_app.py` and executed.
- On `vmb` a file is created by the script `vmb/generate-file.sh` and preserved (= copied to Testbed Host) after the testbed run is completed.
- Two bundled integrations are executed on the Testbed Host that writes to `/tmp/integration`. Also, an Integration is dynamically loaded from `integration/loadable_integration.py` and executed.
- Applications on `vmb` are started with dependencies:
  1. `vmb-iperf3-client` is started after the iPerf3 server is started on `vma`
  2. `procmon-vmb` is started with a 5-second delay, after the `vmb-iperf3-client` is finished
  3. `generate-file` is started with a 20-second delay, after `procmon-vmb` is started (in other words: approx 25 seconds after `vmb-iperf3-client` is finished)
- The Application `vma-iperf3-server` is executed as a Daemon (`null` runtime)

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
    ./im-installer.py -i <path/to/your/baseimage> -o /images/debian.qcow2 -p ../instance-manager/instance-manager.deb
    ```

3. Load required environment variable (define an experiment tag):
    ```bash
    export EXPERIMENT_TAG=hardware_test
    ```

4. Start the testbed:
   ```bash
   cd proto-testbed/setups/sample
   ./proto-testbed -e $EXPERIMENT_TAG -p preserve .
   ```
   After the testbed is completed the file `preserve/vmb/root/output.txt` should be created on the Testbed Host. Also, check the contents of `/tmp/integration` created by both bundled Integrations.

5. Export the results (and clean up):
   ```bash
   ./proto-testbed export -e $EXPERIMENT_TAG -o ./${EXPERIMENT_TAG}-images image setups/example1
   ./proto-testbed export -e $EXPERIMENT_TAG -o ./${EXPERIMENT_TAG}-csvs csv setups/example1 

    # Optional: Clean up data from InfluxDB (Should be done before repeating the experiment)
   ./proto-testbed clean -e $EXPERIMENT_TAG

    # Optional: Delete disk images (After all experiments are completed)
    rm /images/debian.qcow2
    # Optional: Delete preserved files
    rm -rf preserve
   ```
