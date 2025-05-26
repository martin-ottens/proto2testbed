# Proto²Testbed in Docker

Proto²Testbed can be used inside Docker Containers, so that no local installation is required. Since it needs to use the KVM subsystem and modify the network configuration of the host machine, the containers run in privileged mode, e.g., have effective root privileges on the machine.
The system requirements described in `/README.md` must also be met when using Docker.

## Build the Docker Images
Run the Docker builds from the root of the repo.
```bash
docker build -f docker/Dockerfile.p2t -t p2t:latest .
docker build -f docker/Dockerfile.genimg -t p2t-genimg:latest .
```

## Generate a Disk Image using Docker
```bash
docker run --rm --privileged \
    -v /images:/images \
    -e </path/to/additional_deps>:/app \
    p2t-genimg:latest \
        -e /app/extra.commands \
        -i /images/debian-template.qcow2 \
        -o /images/<output_image>
```
The entrypoint of the image is `p2t-genimg -p <Instance Manager Package>`, additional `p2t-genimg` arguments are passed to the executable. The Instance Manager package is built into the Docker image and will be installed automatically.
Some more details:
- `--privileged` will also grant access to `/dev/kvm`.
- `-v /images:/images` is used for the disk image library. The result image is also written to the library.
- Since there are never any relevant modifications inside the container, `--rm` can be used to delete the container after the disk image was created.

## Execute a Testbed using Docker
```bash
docker run -it --net host --rm --privileged \
    -e EXPERIMENT_TAG=<tag> \
    -v /images:/images \
    -v /tmp/p2t:/tmp/p2t \
    -v </path/to/your/testbed_package>:/app \
    p2t:latest run <additional args> /app
```

The entrypoint of the image is `p2t`, additional Proto²Testbed subcommands are passed to the executable.
Some more details:
- There is no InfluxDB installed inside the container. Provide an external InfluxDB for result storage, connection settings can be specified using the environment variables `INFLUXDB_DATABASE`, `INFLUXDB_HOST`, `INFLUXDB_PORT`, `INFLUXDB_USER` and `INFLUXDB_PASSWORD`.
- `--net host` is used, so that the container can access all interfaces of the host machine and create network bridges. It also accesses the InfluxDB from the host's network (e.g. an InfluxDB instance installed on the host machine, possible in Docker with an exposed port).
- `--privileged` will also grant access to `/dev/kvm`.
- `-v /images:/images` is used for the disk image library.
- `-v /tmp/p2t:/tmp/p2t` is used to share some states (e.g. VSOCK CIDs, since there is no CID registry in Linux) across multiple containers. This also allows the execution of `p2t ls` inside a container.
- ` -v </path/to/your/testbed_package>:/app` mount the testbed package. If file preservation is enabled, Proto²Testbed running in the container will write to that mount on the host machine.
- Since there are never any relevant modifications inside the container, `--rm` can be used to delete the container after the testbed was executed.
- The experiment tag can be set using `-e EXPERIMENT_TAG=<tag>`, alternatively, it is possible to use the normal Proto²Testbed argument `-e <tag>`.
