# Ignition App

**Language:** Python

## Overview

Configures an Inductive Automation Ignition Gateway 8.3 SCADA master at experiment start.
The app discovers DNP3 outstation (RTU) IP addresses from the topology and renders
device-connections per RTU. With `perspective`, the app additionally generates a basic
Perspective HMI. To facilitate HMI building, tags are imported automatically (from the
returned DNP3 points). A generated sync tag periodically browses each device on the OPC
server and mirrors every point into the `[default]` provider.

Alternatively, if `gwbk` points at a hand-authored gateway backup, the app injects it
untouched and restores it at boot via `gwcmd.bat -s <file> -m`.

## Spec / Configuration

```yaml
spec:
  scenario:
    apps:
      - name: ignition
        hosts:
          - hostname: OT-scada
            metadata:
              type: gateway
              connected_rtus:
                - rtu-1             # plain hostname, defaults below
                - hostname: rtu-2   # or per-RTU overrides
                  name: custom-name
                  port: 20000
                  source_address: 1
                  destination_address: 1024
                  interface: eth0
              perspective: true     # optional HMI; or an options object:
              # perspective:
              #   project: hmi
              #   open_client: true
              # OR (mutually exclusive with connected_rtus and perspective)
              # restore a hand-authored backup verbatim:
              # gwbk: /phenix/injects/${BRANCH_NAME}/ignition/base.gwbk
          - hostname: hmi-1
            metadata:
              type: perspective     # dedicated HMI desktop (optional)
              # connected_gateway: OT-scada   # only needed with >1 HMI gateway
```

### `type: gateway`

| Option           | Default   | Description                                                                  |
|------------------|-----------|------------------------------------------------------------------------------|
| `type`           | `gateway` | Host role; `gateway` or `perspective`                             |      
| `connected_rtus` | `[]`      | RTUs to connect to; plain hostname strings or override objects (below).      |
| `perspective`    | (none)    | Generate a basic Perspective HMI; `true` for defaults or an options object (below). Requires `connected_rtus`. |
| `gwbk`           | (none)    | Path on the phenix host to a complete `.gwbk` to restore verbatim. Mutually exclusive with `connected_rtus` and `perspective`. |

#### `connected_rtus` entries

| Option                | Default          | Description                                          |
|-----------------------|------------------|------------------------------------------------------|
| `hostname`            | (required)       | Topology hostname of the outstation.                 |
| `name`                | hostname         | Ignition device name; tags reference it (e.g. `[custom-name]AnalogInput0`). |
| `port`                | `20000`          | Outstation TCP port.                                 |
| `source_address`      | `1`              | DNP3 master address (ot-sim default).                        |
| `destination_address` | `1024`           | DNP3 outstation address (ot-sim default).            |
| `interface`           | first interface  | Which topology interface's address to connect to.    |

#### `perspective:` options

| Option        | Default | Description                                                            |
|---------------|---------|------------------------------------------------------------------------|
| `project`     | `hmi`   | Ignition project name; the HMI is served at `http://<gateway>:8088/data/perspective/client/<project>`. |
| `open_client` | `true`  | Also auto-open the HMI in Firefox on the gateway's own console at boot. |

### `type: perspective`

| Option              | Default         | Description                                            |
|---------------------|-----------------|--------------------------------------------------------|
| `connected_gateway` | (auto)          | Gateway hostname to point at; only required when more than one gateway has `perspective` enabled. |
| `interface`         | first interface | Which *gateway* interface's address to use in the URL. |

## HMI

### Tag auto-import

The HMI browses the `[default]` tag provider at runtime, and the provider is populated on
the gateway rather than at build time. The app seeds the provider with a `_TagSync_`
expression tag whose `valueChanged` event script runs every 30 seconds: for each
configured device it browses the OPC server and mirrors every point it finds into the
provider with a merge.

### Perspective dashboards

A basic Perspective HMI is generated with:
* an overview tab (per-RTU connection status table)
* one dashboard tab per RTU showing every tag's value
* a simple popup for sending commandes. Double-clicking any row in a dashboard opens
the DNP3 command popup to send either:
  * DNP3 CROB commands
  * on-demand class/integrity data polls

### Browser auto-open

With `open_client` (and on every `type: perspective` host) a startup script at
`/phenix/startup/99-ignition-perspective.ps1` opens the HMI URL in Firefox at boot.

## Testing

Unit tests live in `tests/`:

```bash
pytest phenix_apps/apps/ignition/tests
```

`tests/test_ignition_input.yaml` is a sample experiment for manual dry-runs against the
full app entry point, without a live phenix system:

```bash
PHENIX_LOG_FILE="" phenix-app-ignition pre-start --dry-run < phenix_apps/apps/ignition/tests/test_ignition_input.yaml
```

## Dependencies

### Images

* Only developed and tested with Igntion 8.3.1.
* Only works for Windows hosts.
* Only works for DNP3 outstations.
* Expects VMs configured to run all scripts in `C:\phenix\startup` and `C:\phenix\user-startup` at boot.
* Expects `firefox.exe` in the path.
* Expects the ignition service to start automatically at boot.
