# Ignition App

**Language:** Python

## Overview

Configures an Inductive Automation Ignition Gateway 8.3 SCADA master at experiment start.
The app discovers DNP3 outstation (RTU) IP addresses from the topology and renders
device-connections per RTU. With `perspective`, the app additionally generates a basic
Perspective HMI. To facilitate HMI building, tags are imported automatically (from the
returned DNP3 points). A generated sync tag periodically browses each device on the OPC
server and mirrors every point into the `[default]` provider.

With `api`, a small WebDev resource exposes DNP3 over HTTP: a `GET` reads every point, and
a `POST` issues a DNP3 control command. It is independent of `perspective` and works on
its own.

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
              api: true             # optional WebDev tag API; or an options object:
              # api:
              #   auth: true
              #   roles: [Administrator]
              # OR (mutually exclusive with connected_rtus, perspective, and api)
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
| `api`            | (none)    | Serve a WebDev tag API; `true` for defaults or an options object (below). Independent of `perspective` and `connected_rtus`. |
| `gwbk`           | (none)    | Path on the phenix host to a complete `.gwbk` to restore verbatim. Mutually exclusive with `connected_rtus`, `perspective`, and `api`. |

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

#### `api:` options

| Option        | Default   | Description                                                                          |
|---------------|-----------|--------------------------------------------------------------------------------------|
| `auth`        | `false`   | Require HTTP Basic auth on the `POST` (control) endpoint; reads stay open.            |
| `roles`       | `[]`      | When `auth` is set, restrict control to users holding at least one of these roles.   |
| `user_source` | `default` | Gateway User Source profile that `auth` validates credentials against.               |

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

## REST API

With `api`, a `tags` WebDev resource is served at
`http://<gateway>:8088/system/webdev/api/tags`. It needs neither `perspective` nor a
pre-populated tag provider.

**`GET`** reads points straight from the OPC server, keyed by device then OPC item path.
Optional `?device=<name>` limits the response to one device.

```bash
# every point on every device
curl http://<gateway>:8088/system/webdev/api/tags

# just one device
curl 'http://<gateway>:8088/system/webdev/api/tags?device=rtu-1'
```

**`POST`** issues a DNP3 command through the driver (a binary CROB). The body names the
Ignition device and the point index; the remaining fields default to a latch-on close:

| Field        | Default | Description                                        |
|--------------|---------|----------------------------------------------------|
| `deviceName` | `DNP3`  | Ignition device name (the RTU's `name`).           |
| `index`      | (req'd) | DNP3 output index.                                 |
| `tcc`        | `1`     | Trip/close code: 0 NUL, 1 CLOSE, 2 TRIP.           |
| `opType`     | `3`     | 0 NUL, 1 PULSE_ON, 2 PULSE_OFF, 3 LATCH_ON, 4 LATCH_OFF. |
| `count`      | `1`     | Operation count.                                   |
| `onTime`     | `1000`  | On time (ms).                                      |
| `offTime`    | `1000`  | Off time (ms).                                     |

```bash
curl -X POST http://<gateway>:8088/system/webdev/api/tags \
     -H 'Content-Type: application/json' \
     -d '{"deviceName": "rtu-1", "index": 0, "opType": 3}'
```

With `auth: true`, the `POST` endpoint requires HTTP Basic credentials, validated against
`user_source` (optionally restricted to `roles`); reads stay open. Pair it with the
gateway's HTTPS port so credentials do not travel in the clear:

```bash
curl -u operator:secret -X POST https://<gateway>:8043/system/webdev/api/tags \
     -H 'Content-Type: application/json' \
     -d '{"deviceName": "rtu-1", "index": 0, "opType": 4}'
```

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
* `api` requires the WebDev module installed and enabled on the gateway.
* Expects VMs configured to run all scripts in `C:\phenix\startup` and `C:\phenix\user-startup` at boot.
* Expects `firefox.exe` in the path.
* Expects the ignition service to start automatically at boot.
