# Proto²Testbed GitLab CI/CD Integration

> **Notice:** The runner will be run with effective root privileges. Depending on configuration of the repo and pipeline, all persons with access to the GitLab repo could obtain full root access to the server executing the runner.#

This document describes how the Proto²Testbed Docker images can be used to integrate the testbed framework into GitLab CI/CD workflows. The use of Integrations is not possible in this setup.

## Installation

1. Install GitLab-Runner as described [here](https://docs.gitlab.com/runner/install/linux-repository.html).
2. Due to the size of disk images, they should not be up- and downloaded as GitLab artifacts. It is recommended to store disk images at a central location of the runners file system, e.g. at `/images` (this path is used in this setup example). There you could also place and maintain a general base OS installation disk image. The generation of such a base OS installation disk image is described in `baseimage-creation/README.md`. When using multiple runner hosts, the image directory should be shard across all hosts, e.g., using NFS.
3. For optimal performance, enable the `vhost_vsock` kernel module on the runner host.
4. Make sure the GitLab-Runner is started, register it in GitLab using
    ```bash
     gitlab-runner register --executor "docker"
    ```
   Add a tag to the runner to indicate that it is capable to run Proto²Testbeds, e.g., *p2t*.
4. Change the GitLab-Runner configuration located at `/etc/gitlab-runner/config.toml`:
   - Select a suitable `concurrent` count. Do not over-provision the hardware.
   - Set `runners.docker/privildged` to *true* (grants access to network device management and access to `/dev/kvm`)
   - Set `runners.docker/network_mode` to *host* (use the root network namespace of the runner's host system)
   - Add */images:/images* and */tmp/p2t:/tmp/p2t* to `runners.docker/volumes`
5. The GitLab-Runner should reload the config by itself. If not, restart the runner.

### Example GitLab-Runner Config
```toml
concurrent = 4 # Select a suitable value
check_interval = 0
connection_max_age = "15m0s"
shutdown_timeout = 0

[session_server]
  session_timeout = 1800

[[runners]]
  # ... skipped register settings ...
  executor = "docker"
  # ... skipped [runners.cache] ...
  [runners.docker]
    tls_verify = false
    image = "debian:latest"
    privileged = true
    disable_entrypoint_overwrite = false
    oom_kill_disable = false
    disable_cache = false
    volumes = [
      "/cache",
      "/images:/images",
      "/tmp/p2t:/tmp/p2t"
    ]
    shm_size = 0
    network_mtu = 0
    network_mode = "host"
```

## Sample CI/CD Configs

### Image Generation
This example creates an experiment-specific disk image using the `p2t-genimg` Docker image. The disk image is based on a basic OS installation disk image located at `/image/debian-template.qcow2` and is written to `/images/debian-<BRANCH_NAME>.qcow2`.
See `baseimage-creation/README.md` *im-installer.py* for details on how to use `p2t-genimg` tool.

```yml
# ...
variables:
  IMAGE_LIBRARY: "/images"
  TEMPLATE_IMAGE: "debian-template.qcow2"

generate-image:
 image: 
    name: martinottens/proto2testbed:genimg
    entrypoint: [""]
  tags: ["p2t"]
  needs: []
  stage: prepare
  script:
    - p2t-genimg 
      --input ${IMAGE_LIBRARY}/${TEMPLATE_IMAGE} 
      --output ${IMAGE_LIBRARY}/debian-${CI_COMMIT_BRANCH}.qcow2
      --package /im.deb
      --mount ${CI_PROJECT_DIR}/prepare
      --extra ${CI_PROJECT_DIR}/prepare/extra.commands
      --timeout 240
```

### Testbed Execution
This example executes a testbed based on the previously created experiment-specific disk image. This job actually runs four experiments in parallel using the *parallel.marix* feature in GitLab: The variables defined in the *parallel-tags* matrix are used in the testbed configuration file by using `{{ PLACEHOLDERS }}`.

Preserve files and CSVs of InfluxDB time series are exported and stored as pipeline artifacts for later analysis. To prevent interferences with parallel running testbeds, GitLab's unique *CI_JOB_ID* is used as the experiment tag. After the main script is completed or failed, the *after_script* is executes, which attempts to clear the data from the InfluxDB and removes remains of dangling testbed runs.

```yml
# ...
start-experiments:
  needs: ["generate-image"]
  image:
    name: martinottens/proto2testbed:p2t
    entrypoint: [""]
  tags: ["p2t"]
  stage: execute
  parallel:
    matrix:
      - SETUP: ["Testcase1", "Testcase2"]
        EXPERIMENT: ["Delay", "Throughput"]
  variables:
    TEMPLATE: "template/"
    OUTPUT_PATH: "${ARTIFACTS_PATH}/${SETUP}-${EXPERIMENTS}"
    EXPERIMENT_TAG: "$CI_JOB_ID"
  script:
    - p2t run -p $OUTPUT_PATH -e $EXPERIMENT_TAG ${CI_PROJECT_DIR}/testbed
    - p2t export csv -e $EXPERIMENT_TAG -o $OUTPUT_PATH ${CI_PROJECT_DIR}/testbed
  after_script:
    - p2t clean -e $EXPERIMENT_TAG
    - p2t prune --all --interfaces -vv # Optional: Clean dangling testbeds on that host
  artifacts:
    paths:
      - "$OUTPUT_PATH"
    expire_in: 2h
```
