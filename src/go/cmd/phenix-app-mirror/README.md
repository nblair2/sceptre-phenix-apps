### mirror

The `mirror` app configures cluster-wide packet mirroring for specific VLANs
to a specific interface on a predefined node using GRE tunnels.

For example, let's assume the app is configured as follows in the scenario
file:

```yaml
apiVersion: phenix.sandia.gov/v2
kind: Scenario
metadata:
  name: foobar
  annotations:
    topology: traffic-gen
spec:
  apps:
  - name: mirror
    hosts:
    - hostname: monitor
      metadata:
        interface: IF0
        vlans:
        - EXP_1
```

Given the above configuration, each cluster host participating in the
experiment except for the cluster host the `monitor` VM is scheduled on will
create a GRE tunnel port in OVS to the cluster host the `monitor` VM is
scheduled on. Each cluster host will also create an OVS mirror that includes
taps from all VMs with an interface in the `EXP_1` VLAN that are not routers
or firewalls, using the GRE tunnel as the destination port for the mirrored
traffic, except for the cluster host the `monitor` VM is scheduled on, which
will instead use the tap of the `IF0` interface for the `monitor` VM as the
mirror destination.

#### External IPv4 destinations

The `mirror` app can also forward mirrored VLAN traffic to external IPv4
addresses (e.g. a dedicated physical capture appliance) via a GRE tunnel.
External destinations are configured under `metadata.external` in the app
block and are independent of the `hosts` list.

```yaml
spec:
  apps:
  - name: mirror
    hosts:
    - hostname: monitor
      metadata:
        interface: IF0
        vlans:
        - EXP_1
    metadata:
      external:
      - ip: 192.168.192.168
        protocol: gre
        metadata:
          vlans:
          - WAN
          - LAN2
      - ip: 10.10.10.50
        protocol: gre
        metadata:
          vlans:
          - EXP_1
```

For each entry under `metadata.external` the app will:

1. Create a GRE tunnel OVS port on every cluster host pointing to the
   external `ip`.
2. Create an OVS mirror on each cluster host that selects all traffic on the
   listed VLANs and forwards it through the tunnel.

The OVS port and mirror are named deterministically as
`ext-<hex-encoded-IPv4>` (e.g. `ext-c0a8c0a8` for `192.168.192.168`), which
keeps names ≤15 characters and avoids collisions between destinations.

**Supported protocols:** `gre` only.  ERSPAN and GTP-U require specific kernel
and OVS version support that cannot be assumed across all deployments; the
existing per-host `erspan` configuration block is still available for VM
destinations that need ERSPAN.

**Host networking prerequisite:** the physical network path from every cluster
host to the external IP must be routable.  The cluster host's default network
interface (not the OVS bridge) is used as the GRE tunnel source.

**Limitations:**
- Only IPv4 external destinations are supported (GRE over IPv4).
- Each external `ip` must be unique within the `external` list.
- VLANs listed under `metadata.vlans` must exist in the experiment topology.
- External mirrors capture all traffic on the selected VLANs, not just traffic
  from specific VMs.