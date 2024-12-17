# Proto²Testbed Commands

There are several ways to interact with Proto²Testbed, the options depend on the configuration and the phase the testbed is currently in.

## Top-Level Controller Commands
In the most cases, users will interact with Proto²Testbed by using the CLI of the Testbed Controller. 
It is invoked with the command `p2t <subcommand> <arguments>` (or `proto-testbed <subcommands> <arguments>` when not installed globally). 
*Arguments* can be common for all subcommands or subcommand specific. The following arguments can be used for all subcommands:
- **`--verbose`/`-v`**: Increase verbosity of log outputs for debugging (`-vv` to show even more log messages)
- **`--sudo`**: Prepend `sudo` to all commands executed by Proto²Testbed that require privileges (Note: No interactive authentication is possible)
- **`--influxdb <path>`**: Path to an InfluxDB JSON config (e.g., for using an external database with authentication). See `controller/assets/influxdb.schema.json` for a schema of that config. InfluxDB's parameters can also be changed by setting the environment variables `INFLUXDB_DATABASE`, `INFLUXDB_HOST`, `INFLUXDB_PORT`, `INFLUXDB_USER` and `INFLUXDB_PASSWORD`.
- **`--experiment`/`-e <experiment tag>`**: Experiment Tag used for the subcommand (e.g., for labeling data produced by a testbed run or exporting specific data from the database)

The following subcommands are available in Proto²Testbed, some of them require privileges for execution. You can always append `-h` to see all available subcommands.

### `run <TESTBED_CONFIG>`
Execute a testbed with the Testbed Package located at `TESTBED_CONFIG`. This command requires privileges. 
The following subcommands are available:
- **`--interact`/`-i <stage>`**: Pause the testbed execution after a specific stage is completed (or if an error occurs). During this pause you can interact via a Terminal with the Instances as if they were normal computers. The following stages can be specified:
  - `SETUP`: Pause after the Instances were started, but before the setup script is called.
  - `INIT`: Pause after the setup scripts were executed, and all Applications are installed, but before the Experiments are started.
  - `EXPERIMENT`: Pause after the experiment is completed, just before the testbed is dismantled.
  - `DISABLE`: Do not pause.
- **`--preserve`/`-p <directory>`**: Preserved files (specified in the Testbed Configuration or during an experiment by scripts or Applications) will be stores in this directory. A subdirectory with the name of each Instance will be created.
- **`--skip_integrations`/`-s`**: Skip the execution of Integrations on the Testbed Host
- **`--dont_store`/`-d`**: Don't push any data into the InfluxDB.
- **`--skip_substitution`**: Don't replace placeholders in the Testbed Configuration. If an invalid JSON file results from this, the startup will fail.
- **`--no_kvm`**: Disable KVM virtualization (e.g., when using Proto²Testbed on a virtual machine). Performance will be severely degraded.

### `list`
List all testbeds that are currently running on the host with some details. 
Normally, only the testbeds started by the current user will be listed. Add `--all` or `-a` to see all running testbeds on the host.

### `attach <INSTANCE_NAME>`
Attach to the console of the Instance `INSTANCE_NAME` (e.g., when the testbed is paused). If the Instance name is not unique across multiple concurrent testbeds, an experiment tag can be added (using the `-e` argument) to specify the testbed the Instance belongs to.
- **`--ssh`/`-s`**: Normally, a connection is established via a serial console. When the Management Network is enabled, access via SSH is also possible. The serial console can only be attached once. With SSH, multiple connections to the same Instance are possible at a time.
- **`--user`/`-u <username>`**: Username for the SSH connection, defaults to `root`. For serial connections, the `testbed` user with passwordless `sudo` permissions is always used, since it owns the TTY.
- **`--other`/`-o`**: Normally, only Instances from testbeds started by the current user can be attached. Use this argument to allow the attachment of all Instances running on the host.

### `export image|csv <TESTBED_CONFIG>`
Export the data stored in the InfluxDB to Matplotlib plots (= `image`) or CSV files (= `csv`). The Applications described in `TESTBED_CONFIG` will be exported. The following additional arguments can be used:
- **`--output`/`-o <path>`**: The output path for the exports (defaults to `./out`)
- **`--format`/`-f pdf|svg|png|jpeg`**: Select the export format for Matplotlib plots (= `image`) (defaults to `pdf`)
- **`--exclude-instance`/`-ei <instance>`**: Exclude `instance` from the exports. Can be repeated multiple times to exclude multiple Instances.
- **`--exclude-application`/`-ea <application>`**: Exclude `application` from the exports. Can be repeated multiple times to exclude multiple Applications.
- **`--skip_substitution`**: Don't replace placeholders in the Testbed Configuration. If an invalid JSON file results from this, the export will fail.

### `clean`
Delete data from the InfluxDB for a specific experiment tag (specified using the `-e` argument). 
Use `--all` to delete all data from the database (which is the default database from `/etc/proto2testbed/proto2testbed_defaults.json`, the database specified by the `--influxdb` config or via the `INFLUXDB_DATABASE` environment variable).

### `prune`
If unwanted remnants of testbed runs remain on the Testbed Host (files or network interfaces), as can happen after a crash, for example, this subcommand can be used to perform a cleanup. This subcommand requires privileges. The following arguments can be used:
- **`--all`**: Also prune dangling testbeds that were started by other users.
- **`--interfaces`**: Strictly delete all dangling interfaces (matching by name and not by state files)

## Controller Commands in Interactive Mode
When a testbed is started with the `run` subcommand and interaction is enabled during a testbed pause (`--interact <stage>`), a simple CLI is started alongside the log output. The following commands are available:
- **`continue (INIT|EXPERIMENT)`**: Continue with the testbed execution, when `INIT` or `EXPERIMENT` is specified the testbed will pause again at that stage, otherwise it will run to completion.
- **`attach <instance>`**: Attach to an Instance using the serial console connection. When the CLI of the Controller is attached to an Instance, no log messages are printed by the Controller.
- **`copy (instance:)<path> (instance:)<path>`**: Copy a file or directory from the Testbed Host to an Instance or the other way around. More or less works like `scp`.
- **`list`**: List all Instances in the current testbed and their status.
- **`preserve <instance>:<path>`**: Mark a file or directory on an Instance for preservation. It will be copied before the Instance is shut down.
- **`exit`**: Stop the testbed now, do not continue. File preservation will still be performed.
- **`restart`**: The same as exit, but the testbed is restarted with the same configuration and arguments afterwards.

## Instance Manager `im` Commands
On the Instances, the Instance Manager provides the `im` command, that can be used to interact with the Proto²Testbed from within the Instance. 
The purpose of this script is to be used in scripts for manual experiments. The following subcommands are available:

### `status`
Get the current status of the Instance Manager of the Instance.

### `preserve <path>`
Mark the file or directory at `path` for preservation, `path` is copied to the Testbed Host before the Instance is destroyed.

### `log <message>`
Send a log message to the Testbed Controller, it shows up in the `p2t run` log. Additionally, a log level can be specified using `--level`/`-l <level>`, where level is one of `SUCCESS`, `INFO` (default), `WARNING`, `ERROR`, `DEBUG` (only visible if the Controller is started with `-v`).

### `data [NAME:VALUE]`
Push data points to the InfluxDB. A measurement must be specified with `--measurement`/`-m <measurement>`. 
Multiple values in the format `NAME:VALUE` can be added to that measurement, where `NAME` is a string and `VALUE` an integer or float. 
Additional tags can be added using `--tag`/`-tag <NAME:VALUE>`, where `NAME` and `VALUES` are strings. The name of the Instance and the experiment tag are always automatically added as tags. 

### `shutdown`
Shuts down ALL Instances of the current testbed run (is the same as using the `exit` command of the Testbed Controller). 
Use `--restart`/`-r` to restart the testbed (the same as using the `restart` command of the Testbed Controller).
