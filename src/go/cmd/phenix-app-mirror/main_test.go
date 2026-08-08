package main

import (
	"log/slog"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"inet.af/netaddr"
)

func TestFilterVMs(t *testing.T) {
	t.Parallel()

	var (
		log = slog.Default()
		vms = []string{"vm1", "router1", "vm2", "firewall1"}
	)

	getNodeType := func(name string) string {
		switch name {
		case "router1":
			return "router"
		case "firewall1":
			return "firewall"
		default:
			return "vm"
		}
	}

	tests := []struct {
		name     string
		hmd      MirrorHostMetadata
		expected []string
	}{
		{
			name:     "single vlan",
			hmd:      testMetadata([]string{"100"}, false),
			expected: []string{"vm1", "router1", "vm2", "firewall1"},
		},
		{
			name:     "multiple vlans, no mirror routed",
			hmd:      testMetadata([]string{"100", "101"}, false),
			expected: []string{"vm1", "vm2"},
		},
		{
			name:     "multiple vlans, mirror routed",
			hmd:      testMetadata([]string{"100", "101"}, true),
			expected: []string{"vm1", "router1", "vm2", "firewall1"},
		},
		{
			name:     "empty vms",
			hmd:      testMetadata([]string{"100", "101"}, false),
			expected: []string{},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()

			var inputVMs []string
			if tt.name != "empty vms" {
				inputVMs = make([]string, len(vms))
				copy(inputVMs, vms)
			}

			got := filterVMs(log, inputVMs, tt.hmd, "target", getNodeType)
			assert.Equal(t, tt.expected, got)
		})
	}
}

func TestFilterVMs_CaseInsensitive(t *testing.T) {
	t.Parallel()

	log := slog.Default()
	vms := []string{"ROUTER1"}
	hmd := testMetadata([]string{"1", "2"}, false)

	getNodeType := func(_ string) string {
		return "ROUTER"
	}

	got := filterVMs(log, vms, hmd, "target", getNodeType)
	assert.Empty(t, got, "Should filter out ROUTER (case insensitive)")
}

func testMetadata(vlans []string, routed bool) MirrorHostMetadata {
	return MirrorHostMetadata{
		Interface:    "",
		VLANs:        vlans,
		HIL:          nil,
		SetupOVS:     false,
		MirrorRouted: routed,
	}
}

// ---------------------------------------------------------------------------
// ExternalDestination / validateExternalDestinations tests
// ---------------------------------------------------------------------------

func TestValidateExternalDestinations_Valid(t *testing.T) {
	t.Parallel()

	dests := []ExternalDestination{
		{
			IP:       "192.168.1.1",
			Protocol: "gre",
			Metadata: ExternalDestMetadata{VLANs: []string{"LAN"}},
		},
		{
			IP:       "10.0.0.2",
			Protocol: "gre",
			Metadata: ExternalDestMetadata{VLANs: []string{"WAN", "LAN2"}},
		},
	}

	assert.NoError(t, validateExternalDestinations(dests))
}

func TestValidateExternalDestinations_InvalidIP(t *testing.T) {
	t.Parallel()

	dests := []ExternalDestination{
		{
			IP:       "not-an-ip",
			Protocol: "gre",
			Metadata: ExternalDestMetadata{VLANs: []string{"LAN"}},
		},
	}

	assert.Error(t, validateExternalDestinations(dests))
}

func TestValidateExternalDestinations_UnsupportedProtocol(t *testing.T) {
	t.Parallel()

	dests := []ExternalDestination{
		{
			IP:       "1.2.3.4",
			Protocol: "erspan",
			Metadata: ExternalDestMetadata{VLANs: []string{"LAN"}},
		},
	}

	err := validateExternalDestinations(dests)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "unsupported external protocol")
}

func TestValidateExternalDestinations_EmptyVLANs(t *testing.T) {
	t.Parallel()

	dests := []ExternalDestination{
		{
			IP:       "1.2.3.4",
			Protocol: "gre",
			Metadata: ExternalDestMetadata{VLANs: []string{}},
		},
	}

	err := validateExternalDestinations(dests)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "no VLANs specified")
}

func TestValidateExternalDestinations_DuplicateIP(t *testing.T) {
	t.Parallel()

	dests := []ExternalDestination{
		{
			IP:       "1.2.3.4",
			Protocol: "gre",
			Metadata: ExternalDestMetadata{VLANs: []string{"LAN"}},
		},
		{
			IP:       "1.2.3.4",
			Protocol: "gre",
			Metadata: ExternalDestMetadata{VLANs: []string{"WAN"}},
		},
	}

	err := validateExternalDestinations(dests)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "duplicate external destination")
}

func TestValidateExternalDestinations_Empty(t *testing.T) {
	t.Parallel()

	assert.NoError(t, validateExternalDestinations(nil))
	assert.NoError(t, validateExternalDestinations([]ExternalDestination{}))
}

// ---------------------------------------------------------------------------
// externalPortName tests
// ---------------------------------------------------------------------------

func TestExternalPortName(t *testing.T) {
	t.Parallel()

	tests := []struct {
		ip       string
		expected string
	}{
		{"192.168.192.168", "ext-c0a8c0a8"},
		{"10.0.0.1", "ext-0a000001"},
		{"1.2.3.4", "ext-01020304"},
	}

	for _, tt := range tests {
		t.Run(tt.ip, func(t *testing.T) {
			t.Parallel()

			ip := netaddr.MustParseIP(tt.ip)
			got := externalPortName(ip)
			assert.Equal(t, tt.expected, got)
			assert.LessOrEqual(t, len(got), 15, "OVS port name must be ≤15 characters")
		})
	}
}

// ---------------------------------------------------------------------------
// buildExternalMirrorCommand tests
// ---------------------------------------------------------------------------

func TestBuildExternalMirrorCommand_ResolvesVLANs(t *testing.T) {
	t.Parallel()

	log := slog.Default()
	vlansByAlias := map[string]int{"LAN": 100, "WAN": 200}

	cmd := buildExternalMirrorCommand(log, vlansByAlias, "testmirror", "br0", "testmirror", []string{"LAN", "WAN"})

	assert.NotNil(t, cmd)
	assert.Equal(t, "ovs-vsctl", cmd[0])

	joined := strings.Join(cmd, " ")

	assert.Contains(t, joined, "100")
	assert.Contains(t, joined, "200")
	assert.Contains(t, joined, "testmirror")
}

func TestBuildExternalMirrorCommand_UnknownVLAN(t *testing.T) {
	t.Parallel()

	log := slog.Default()
	vlansByAlias := map[string]int{"LAN": 100}

	cmd := buildExternalMirrorCommand(log, vlansByAlias, "testmirror", "br0", "testmirror", []string{"UNKNOWN"})

	assert.Nil(t, cmd, "should return nil when no VLANs resolve")
}
