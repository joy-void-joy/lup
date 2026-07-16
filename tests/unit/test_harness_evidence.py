"""Evidence-ledger version-drift trigger tests."""

from lup_template.devtools.harness.evidence import (
    EVIDENCE_LEDGER,
    EvidenceEntry,
    evidence_drift,
    parse_version,
    sdk_evidence_drift,
)

STALE_LEDGER = [EvidenceEntry(capability="codex-cli", version="0.144.4")]


def test_doctor_flags_an_installed_component_newer_than_the_ledger() -> None:
    drift = evidence_drift("codex-cli", "codex-cli 0.145.0", STALE_LEDGER)

    assert drift is not None
    assert drift.installed == "0.145.0"
    assert drift.accepted == "0.144.4"
    assert "re-probe" in drift.message
    assert "docs/native-capabilities.md" in drift.message


def test_matching_and_older_installed_versions_do_not_drift() -> None:
    assert evidence_drift("codex-cli", "codex-cli 0.144.4", STALE_LEDGER) is None
    assert evidence_drift("codex-cli", "codex-cli 0.143.9", STALE_LEDGER) is None


def test_unknown_capabilities_and_unparseable_banners_stay_silent() -> None:
    assert evidence_drift("novel-cli", "novel-cli 9.9.9", STALE_LEDGER) is None
    assert evidence_drift("codex-cli", "development build", STALE_LEDGER) is None


def test_version_parsing_handles_real_banner_shapes() -> None:
    assert parse_version("codex-cli 0.144.5") == [0, 144, 5]
    assert parse_version("2.1.211 (Claude Code)") == [2, 1, 211]
    assert parse_version("no digits here") is None


def test_longer_component_counts_compare_componentwise() -> None:
    ledger = [EvidenceEntry(capability="claude-cli", version="2.1")]

    assert evidence_drift("claude-cli", "2.1.1", ledger) is not None
    assert evidence_drift("claude-cli", "2.1.0", ledger) is None


def test_sdk_drift_reads_the_installed_distribution() -> None:
    newer = [EvidenceEntry(capability="claude-agent-sdk", version="0.0.1")]
    ancient = [EvidenceEntry(capability="claude-agent-sdk", version="999.0.0")]

    drift = sdk_evidence_drift(newer)
    assert drift is not None and drift.capability == "claude-agent-sdk"
    assert sdk_evidence_drift(ancient) is None


def test_shipping_ledger_carries_every_probed_contract() -> None:
    capabilities = [entry.capability for entry in EVIDENCE_LEDGER]

    assert capabilities == ["claude-cli", "claude-agent-sdk", "codex-cli"]
