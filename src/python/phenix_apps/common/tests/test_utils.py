import itertools

import minimega
import pytest

from phenix_apps.common import utils


class _StubMM:
    """Stand-in for minimega.minimega.

    ``cc_exitcode`` / ``cc_clients`` replay per-call effects: a list (the
    per-host rows that cc fan-out returns) is returned, an Exception is raised
    (a transport-level failure, which propagates regardless of _raise_errors).

    A per-host row carrying a non-empty ``Error`` is raised as a
    ``minimega.Error`` only while ``_raise_errors`` is set, which is exactly the
    binding behavior ``mm_cc_all_hosts`` suppresses.

    ``vm_info`` and ``cc_commands`` return a fixed value, since callers query
    them once per operation rather than in a replayed sequence.
    """

    def __init__(
        self,
        effects=None,
        client_effects=None,
        vm_info_rows=None,
        cc_commands_rows=None,
    ):
        self._effects = list(effects or [])
        self._client_effects = list(client_effects or [])
        self._vm_info_rows = vm_info_rows or []
        self._cc_commands_rows = cc_commands_rows or []
        self._raise_errors = True
        self.calls = 0
        self.client_calls = 0
        self.vm_info_calls = 0
        self.vm_info_kwargs = None

    def _replay(self, effects):
        effect = effects.pop(0)

        # An Exception effect models a transport/namespace failure, which the
        # binding raises whether or not per-host errors are being raised.
        if isinstance(effect, Exception):
            raise effect

        if self._raise_errors:
            for row in effect:
                if row.get("Error"):
                    raise minimega.Error(row["Error"])

        return effect

    def cc_exitcode(self, *_args):
        self.calls += 1

        return self._replay(self._effects)

    def cc_clients(self, *_args):
        self.client_calls += 1

        return self._replay(self._client_effects)

    def cc_commands(self, *_args):
        return self._cc_commands_rows

    def vm_info(self, **kwargs):
        self.vm_info_calls += 1
        self.vm_info_kwargs = kwargs

        return self._vm_info_rows


def _vm_info_row(name, uuid, host="gibson1336"):
    """One `vm info summary` per-host row. The code reads name at index 1 and
    uuid at index 4."""
    return {
        "Host": host,
        "Header": ["id", "name", "state", "uptime", "uuid"],
        "Tabular": [["0", name, "RUNNING", "1m0s", uuid]],
        "Error": "",
    }


def _clients_row(uuid, hostname, host="gibson1336", header=None):
    """One `cc clients` per-host row, with the tabular row derived from the
    header so a caller can drop columns without misaligning the values."""
    header = header or ["uuid", "hostname", "arch", "os"]
    values = {"uuid": uuid, "hostname": hostname, "arch": "amd64", "os": "linux"}

    return {
        "Host": host,
        "Header": header,
        "Tabular": [[values[col] for col in header]],
        "Error": "",
    }


# Multi-host cc_exitcode fan-out: the sibling host that doesn't run the VM
# reports "no client"; only the VM's host carries the code.
_SIBLING_ONLY = [{"Host": "gibson1337", "Error": "no client foo", "Response": ""}]
_WITH_CODE = [
    {"Host": "gibson1337", "Error": "no client foo", "Response": ""},
    {"Host": "gibson1336", "Error": "", "Response": "0"},
]


def test_mm_cc_all_hosts_suppresses_host_errors_and_restores_the_flag():
    # With _raise_errors set (the binding default) a sibling host's "no client"
    # row aborts the whole call and discards the valid row...
    mm = _StubMM([_WITH_CODE])

    with pytest.raises(minimega.Error):
        mm.cc_exitcode("1", "foo")

    # ...which is precisely what mm_cc_all_hosts exists to suppress.
    mm = _StubMM([_WITH_CODE])

    out = utils.mm_cc_all_hosts(mm, mm.cc_exitcode, "1", "foo")

    assert out == _WITH_CODE  # sibling error row NOT dropped
    assert mm._raise_errors is True  # restored after the call


def test_mm_cc_all_hosts_forwards_kwargs():
    mm = _StubMM(vm_info_rows=[_vm_info_row("foo", "abc-1234")])

    utils.mm_cc_all_hosts(mm, mm.vm_info, summary="summary")

    assert mm.vm_info_kwargs == {"summary": "summary"}


def test_mm_cc_exitcode_wait_picks_host_with_code_ignoring_sibling(monkeypatch):
    monkeypatch.setattr(utils.time, "sleep", lambda *_: None)

    # Sibling reports "no client" twice before the VM's host records the code.
    mm = _StubMM([_SIBLING_ONLY, _SIBLING_ONLY, _WITH_CODE])

    row = utils.mm_cc_exitcode_wait(mm, "1", "foo", grace=60.0, poll_rate=0.0)

    assert row["Response"] == "0"
    assert mm.calls == 3


def test_mm_cc_exitcode_wait_transport_error_raises_immediately(monkeypatch):
    monkeypatch.setattr(utils.time, "sleep", lambda *_: None)

    # A transport/namespace error (not a per-host data error) propagates.
    mm = _StubMM([minimega.Error("vm not found: foo")])

    with pytest.raises(minimega.Error):
        utils.mm_cc_exitcode_wait(mm, "1", "foo")

    assert mm.calls == 1


def test_mm_cc_exitcode_wait_grace_exceeded(monkeypatch):
    monkeypatch.setattr(utils.time, "sleep", lambda *_: None)

    # No host ever reports the code (e.g. the client never came back).
    mm = _StubMM([_SIBLING_ONLY] * 5)

    with pytest.raises(RuntimeError):
        utils.mm_cc_exitcode_wait(mm, "1", "foo", grace=0.0, poll_rate=0.0)


def test_mm_cc_exitcode_wait_surfaces_host_errors_in_the_timeout(monkeypatch):
    monkeypatch.setattr(utils.time, "sleep", lambda *_: None)

    # Every host reports a real error -- a command id that never existed, say.
    # mm_cc_all_hosts suppresses the raise and the row scan skips Error rows, so
    # without carrying the text through, a permanent failure is reported as a
    # plain timeout and minimega's actual complaint is thrown away.
    rows = [{"Host": "gibson1336", "Error": "no such command id 99", "Response": ""}]
    mm = _StubMM([rows])

    with pytest.raises(RuntimeError, match="no such command id 99"):
        utils.mm_cc_exitcode_wait(mm, "99", "foo", grace=0.0, poll_rate=0.0)


def test_mm_command_id_reads_data_field():
    # minimega returns the new command id (an int) in the Data field; it must be
    # stringified to match the string id in `cc commands` tabular output.
    resp = [{"Host": "headnode", "Data": 36, "Error": ""}]

    assert utils.mm_command_id(resp) == "36"


def test_mm_command_id_takes_the_first_host_carrying_data():
    # `cc exec` / `cc send` are broadcast, so EVERY host creates its own command
    # and returns its own id in Data -- the ids are per-host counters, not a
    # single namespace-global id. mm_command_id takes the first. That is a known
    # limitation (the ids can legitimately diverge); it is tracked separately and
    # deliberately NOT addressed here.
    resp = [
        {"Host": "gibson1337", "Data": 7, "Error": ""},
        {"Host": "gibson1336", "Data": 7, "Error": ""},
    ]

    assert utils.mm_command_id(resp) == "7"


def test_mm_command_id_missing_data_raises():
    with pytest.raises(RuntimeError):
        utils.mm_command_id([{"Host": "headnode", "Data": None, "Error": ""}])


# cc client returns one per-host response per cluster host; each carries a
# Tabular of registered miniccc clients on that host.
_CLIENTS_EMPTY = [{"Host": "gibson1337", "Header": [], "Tabular": [], "Error": ""}]
_CLIENTS_OTHER = [_clients_row("zzz-9999", "bar", host="gibson1337")]
_CLIENTS_MATCH = [_clients_row("abc-1234", "foo")]
_VM_INFO_FOO = [_vm_info_row("foo", "abc-1234")]


def test_mm_cc_client_active_found_by_hostname():
    mm = _StubMM(client_effects=[_CLIENTS_MATCH], vm_info_rows=_VM_INFO_FOO)

    assert utils.mm_cc_client_active(mm, "foo", grace=60.0, poll_rate=0.0) == "abc-1234"
    assert mm.client_calls == 1


def test_mm_cc_client_active_accepts_a_uuid_with_by_uuid():
    # The name lookup finds nothing (there is no VM called "abc-1234"), which is
    # what tells us the caller handed us a UUID rather than a name.
    mm = _StubMM(client_effects=[_CLIENTS_MATCH], vm_info_rows=_VM_INFO_FOO)

    utils.mm_cc_client_active(mm, "abc-1234", grace=60.0, poll_rate=0.0, by_uuid=True)

    assert mm.client_calls == 1


def test_mm_cc_client_active_by_uuid_still_resolves_a_vm_name():
    # by_uuid used to mean "skip the name lookup", so a caller that passed a VM
    # name with it set -- which the old docstring invited -- could never match
    # anything and was guaranteed to burn the full grace window.
    mm = _StubMM(
        client_effects=[[_clients_row("abc-1234", "site-a-rtr")]],
        vm_info_rows=[_vm_info_row("Site_A.RTR", "abc-1234")],
    )

    got = utils.mm_cc_client_active(
        mm, "Site_A.RTR", grace=0.0, poll_rate=0.0, by_uuid=True
    )

    assert got == "abc-1234"


def test_mm_cc_client_active_matches_router_whose_guest_hostname_differs():
    # THE REGRESSION TEST. A vyatta/minirouter node never gets the phenix
    # hostname script, and RouterName() lowercases and maps '.'/'_' to '-', so
    # the guest reports "site-a-rtr" while minimega knows the VM as
    # "Site_A.RTR". Matching on hostname alone made this VM -- which every other
    # cc call handles fine -- stall for the full 300s grace and then hard-fail.
    mm = _StubMM(
        client_effects=[[_clients_row("abc-1234", "site-a-rtr")]],
        vm_info_rows=[_vm_info_row("Site_A.RTR", "abc-1234")],
    )

    assert (
        utils.mm_cc_client_active(mm, "Site_A.RTR", grace=0.0, poll_rate=0.0)
        == "abc-1234"
    )


def test_mm_cc_client_active_hostname_match_is_case_insensitive():
    # The Go original filters through minicli's `.filter`, which lowercases both
    # sides, so an exact `==` here was stricter than the check it mirrors. The
    # uuid column is absent to force the hostname comparison.
    mm = _StubMM(
        client_effects=[[_clients_row("abc-1234", "foo", header=["hostname"])]],
        vm_info_rows=[_vm_info_row("Foo", "abc-1234")],
    )

    utils.mm_cc_client_active(mm, "Foo", grace=0.0, poll_rate=0.0)


def test_mm_cc_client_active_unknown_vm_fails_fast_without_polling():
    # Mirrors the Go IsC2ClientActive "vm %s does not exist" fast-fail: a typo'd
    # scorch hostname must be an instant, accurate error rather than a 300s stall.
    mm = _StubMM(client_effects=[_CLIENTS_MATCH], vm_info_rows=_VM_INFO_FOO)

    with pytest.raises(RuntimeError, match="does not exist"):
        utils.mm_cc_client_active(mm, "nope", grace=300.0, poll_rate=0.0)

    assert mm.client_calls == 0


def test_mm_cc_client_active_polls_until_visible(monkeypatch):
    monkeypatch.setattr(utils.time, "sleep", lambda *_: None)

    # Two empty rounds (client not yet registered) before it appears.
    mm = _StubMM(
        client_effects=[_CLIENTS_EMPTY, _CLIENTS_OTHER, _CLIENTS_MATCH],
        vm_info_rows=_VM_INFO_FOO,
    )

    utils.mm_cc_client_active(mm, "foo", grace=60.0, poll_rate=0.0)

    assert mm.client_calls == 3


def test_mm_cc_client_active_grace_exceeded(monkeypatch):
    monkeypatch.setattr(utils.time, "sleep", lambda *_: None)

    # Client never appears within the grace window.
    mm = _StubMM(client_effects=[_CLIENTS_EMPTY] * 3, vm_info_rows=_VM_INFO_FOO)

    with pytest.raises(RuntimeError, match="timed out"):
        utils.mm_cc_client_active(mm, "foo", grace=0.0, poll_rate=0.0)


def test_mm_cc_client_active_ignores_non_matching_clients():
    # Other clients are registered, but ours isn't -- must NOT return.
    mm = _StubMM(client_effects=[_CLIENTS_OTHER], vm_info_rows=_VM_INFO_FOO)

    with pytest.raises(RuntimeError, match="timed out"):
        utils.mm_cc_client_active(mm, "foo", grace=0.0, poll_rate=0.0)


def test_mm_vm_uuid_tolerates_a_host_with_no_vms():
    # `vm info summary` leaves Tabular null for a namespace host with zero VMs,
    # which used to raise TypeError before the row could be scanned.
    mm = _StubMM(
        vm_info_rows=[
            {"Host": "gibson1337", "Header": [], "Tabular": None, "Error": ""},
            _vm_info_row("foo", "abc-1234"),
        ]
    )

    assert utils.mm_vm_uuid(mm, "foo") == "abc-1234"
    assert utils.mm_vm_uuid(mm, "absent") is None


# `cc commands` per-host rows: [id, prefix, command, responses, ...].
_CMD_ANSWERED = [
    {"Host": "gibson1337", "Tabular": None, "Error": ""},
    {
        "Host": "gibson1336",
        "Tabular": [["7", "", "[whoami]", "1"]],
        "Error": "",
    },
]
_CMD_UNANSWERED = [
    {
        "Host": "gibson1336",
        "Tabular": [["7", "", "[whoami]", "0"]],
        "Error": "",
    }
]


def test_mm_wait_for_cmd_returns_once_a_host_reports_a_response():
    # Also covers a sibling host whose Tabular is null.
    mm = _StubMM(cc_commands_rows=_CMD_ANSWERED)

    utils.mm_wait_for_cmd(mm, "7", poll_rate=0.0)


def test_mm_wait_for_cmd_is_bounded_by_default(monkeypatch):
    # Previously timeout defaulted to 0.0, which disabled the guard entirely and
    # polled forever -- the scorch cc/caldera cc_send path hung indefinitely on a
    # dead miniccc agent, with no log line and no outer timeout to break it.
    monkeypatch.setattr(utils.time, "sleep", lambda *_: None)
    monkeypatch.setattr(utils.time, "monotonic", itertools.count(0, 1000).__next__)

    mm = _StubMM(cc_commands_rows=_CMD_UNANSWERED)

    with pytest.raises(RuntimeError, match="mm_wait_for_cmd"):
        utils.mm_wait_for_cmd(mm, "7", poll_rate=0.0)

    assert utils.CC_CMD_GRACE > 0
