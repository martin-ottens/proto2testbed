# Proto²Testbed GitLab CI/CD Integration

> **Notice:** The Runner will be run as root. Depending on configuration of the repo and pipeline, all persons with access to the GitLab repo will have full root control over the testbed host by design. 

## Installation

1. Install GitLab-Runner as described [here](https://docs.gitlab.com/runner/install/linux-repository.html).
2. Install Proto²Testbed as described in the `README.md` (using the installer script)
2. Register the GitLab Runner as a shell runner for the project. Per default, `concurrent` is set to `1`, you can update it to a suitable value (see `/etc/gitlab-runner/config.toml` and host requirements in the projects `README.md`).
3. Start the GitLab-Runner as `root` user by changing `"--user" "gitlab-runner"` to `"--user" "root"` in `/etc/systemd/system/gitlab-runner.service`. Restart the runner:
    ```bash
    systemctl daemon-reload
    systemctl restart gitlab-runner.service
    ```
4. Due to the size of disk images, they should not be up- and downloaded as GitLab artifacts. It is recommended to store disk images at a central location of the runners file system, e.g. at `/images`. There you could also place and maintain a general base OS installation disk image.

## Sample Config

Below is a complex example of a `.gitlab-ci.yml` file. The variables defined in the *parallel-tags* matrix is used in the testbed configuration by using `{{ PLACEHOLDERS }}`.

In this example, a basic OS installation image is located at `/images/debian-template.qcow2`. Experiment-specific images are created from this file during the pipeline is executed - after the pipeline is completed, these images are deleted.

```yml
stages:
  - build
  - run
  - export
  - cleanup

default:
  tags: [proto-testbed-host]

variables:
  INFLUXDB_DATABASE: "testbed"
  INFLUXDB_EXPERIMENT: $CI_PIPELINE_ID
  BASE_IMAGE: "/images/debian-template.qcow2"
  PIPELINE_STORAGE_BASE: /tmp/$CI_PIPELINE_ID
  TESTBED_CONFIG_BASE: ./setup

.parallel-tags: &parallel-tags
  parallel:
    matrix:
      - EXPERIMENT_TAG: default
        IMAGE_CLIENT: debian-default.qcow2
        IMAGE_ROUTER: debian-default.qcow2
        WIREGUARD_A: disable
        WIREGUARD_B: disable
        IPERF_HOST: "10.0.1.1"
        PING_TARGET: "10.0.1.1"
        PING_SOURCE: "10.0.2.1"
        VM_CORES: 2
      - EXPERIMENT_TAG: wireguard
        IMAGE_CLIENT: debian-wireguard.qcow2
        IMAGE_ROUTER: debian-default.qcow2
        WIREGUARD_A: "192.168.0.1"
        WIREGUARD_B: "192.168.0.2"
        IPERF_HOST: "192.168.0.1"
        PING_TARGET: "192.168.0.1"
        PING_SOURCE: "192.168.0.2"
        VM_CORES: 2

.build-defaults: &build-defaults
  stage: build
  script:
    - "curl -O --header \"PRIVATE-TOKEN: $EXTERNAL_ACCESS_TOKEN\" $CI_API_V4_URL/your-instance-manager-build-project/jobs/artifacts/main/raw/instance-manager/instance-manager.deb?job=build-manager-package"
    - mkdir -p $PIPELINE_STORAGE_BASE
    - p2t-genimg --input $BASE_IMAGE --output $PIPELINE_STORAGE_BASE/$TARGET_IMAGE --extra $EXTRA_COMMANDS $PIPELINE_STORAGE_BASE/$TARGET_IMAGE ./instance-manager.deb
  retry:
    max: 1
    exit_codes: 1

build-default-image:
  variables:
    EXTRA_COMMANDS: "default.extra"
    TARGET_IMAGE: "debian-default.qcow2"
  <<: *build-defaults

build-wireguard-image:
  variables:
    EXTRA_COMMANDS: "wireguard.extra"
    TARGET_IMAGE: "debian-wireguard.qcow2"
  <<: *build-defaults

experiment:
  stage: run
  tags: [proto-testbed-host]
  needs: [build-default-image, build-wireguard-image]
  <<: *parallel-tags
  script:
    - p2t run -d preserved_files --experiment ${CI_PIPELINE_ID}-${EXPERIMENT_TAG} $TESTBED_CONFIG_BASE
  artifacts:
    paths:
      - "preserved_files"
    expire_in: 1 day

export-results:
  stage: export
  needs: [experiment]
  <<: *parallel-tags
  script:
    - result_renderer.py --config $TESTBED_CONFIG_BASE/testbed.json --influx_database $INFLUXDB_DATABASE --experiment ${CI_PIPELINE_ID}-$EXPERIMENT_TAG --renderout ./images
    - result_export.py --config $TESTBED_CONFIG_BASE/testbed.json --influx_database $INFLUXDB_DATABASE --experiment ${CI_PIPELINE_ID}-$EXPERIMENT_TAG --output ./csvs
  artifacts:
    paths:
      - "images/"
      - "csvs/"
    expire_in: 1 day

.cleanup-defaults: &cleanup-defaults
  stage: cleanup
  variables:
    GIT_STRATEGY: none
  dependencies: []
  <<: *parallel-tags
  script:
    - rm -rfv $PIPELINE_STORAGE_BASE || true
    - p2t clean --experiment ${CI_PIPELINE_ID}-$EXPERIMENT_TAG

cleanup-success:
  needs: [export-results]
  when: on_success
  <<: *cleanup-defaults

cleanup-failure:
  when: on_failure
  <<: *cleanup-defaults
```
