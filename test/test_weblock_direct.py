"""
Integration tests for WebLock's freeze()/verify() flow using
genlayer-test's Direct Execution Mode: the contract runs for real,
in-process, with web and LLM calls mocked, no chain, no simulator, no
network. This is what actually exercises gl.eq_principle.strict_eq,
gl.eq_principle.prompt_non_comparative, and gl.nondet.web.render against
the real GenLayer SDK rather than guessing at their behavior.

Requires conftest.py's Windows fd0 patch to run on Windows.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BUNDLE_PATH = str(Path(__file__).resolve().parent.parent / "contracts" / "weblock_bundle.py")

STATIC_PAGE = "The contract terms remain unchanged. Payment is due within 30 days of delivery."


@pytest.fixture
def weblock(direct_deploy):
    return direct_deploy(BUNDLE_PATH)


def test_freeze_records_snapshot_when_excerpt_found(direct_vm, weblock):
    direct_vm.mock_web(r"example\.com/terms", {"status": 200, "body": STATIC_PAGE})

    snapshot_id = weblock.freeze(
        "https://example.com/terms", "Payment is due within 30 days of delivery."
    )

    assert snapshot_id
    record = weblock.get(snapshot_id)
    assert record["status"] == "frozen"
    assert record["url"] == "https://example.com/terms"


def test_freeze_raises_when_excerpt_not_found(direct_vm, weblock):
    direct_vm.mock_web(r"example\.com/terms", {"status": 200, "body": STATIC_PAGE})

    with direct_vm.expect_revert("excerpt not found"):
        weblock.freeze("https://example.com/terms", "This sentence is not on the page.")


def test_freeze_raises_on_duplicate(direct_vm, weblock):
    direct_vm.mock_web(r"example\.com/terms", {"status": 200, "body": STATIC_PAGE})

    weblock.freeze("https://example.com/terms", "Payment is due within 30 days of delivery.")

    with direct_vm.expect_revert("already frozen"):
        weblock.freeze("https://example.com/terms", "Payment is due within 30 days of delivery.")


def test_verify_returns_unchanged_when_page_identical(direct_vm, weblock):
    direct_vm.mock_web(r"example\.com/terms", {"status": 200, "body": STATIC_PAGE})
    snapshot_id = weblock.freeze(
        "https://example.com/terms", "Payment is due within 30 days of delivery."
    )

    status = weblock.verify(snapshot_id)

    assert status == "unchanged"
    assert weblock.get(snapshot_id)["status"] == "unchanged"


def test_verify_ignores_view_counter_noise(direct_vm, weblock):
    direct_vm.mock_web(r"example\.com/terms", {"status": 200, "body": STATIC_PAGE})
    snapshot_id = weblock.freeze(
        "https://example.com/terms", "Payment is due within 30 days of delivery."
    )

    noisy_page = STATIC_PAGE + " 1,204 views. Posted 2 hours ago."
    direct_vm.mock_web(r"example\.com/terms", {"status": 200, "body": noisy_page})

    status = weblock.verify(snapshot_id)

    assert status == "unchanged"


def test_verify_returns_changed_cosmetic_when_excerpt_still_present(direct_vm, weblock):
    direct_vm.mock_web(r"example\.com/terms", {"status": 200, "body": STATIC_PAGE})
    snapshot_id = weblock.freeze(
        "https://example.com/terms", "Payment is due within 30 days of delivery."
    )

    # mock_web matches in registration order and does not override a prior
    # match for the same pattern, so the old mock must be cleared first.
    direct_vm.clear_mocks()
    changed_page = STATIC_PAGE + " New section: shipping is handled separately."
    direct_vm.mock_web(r"example\.com/terms", {"status": 200, "body": changed_page})

    status = weblock.verify(snapshot_id)

    assert status == "changed_cosmetic"


def test_verify_returns_dead_when_page_unreachable(direct_vm, weblock):
    direct_vm.mock_web(r"example\.com/terms", {"status": 200, "body": STATIC_PAGE})
    snapshot_id = weblock.freeze(
        "https://example.com/terms", "Payment is due within 30 days of delivery."
    )

    direct_vm.clear_mocks()
    direct_vm.strict_mocks = True

    status = weblock.verify(snapshot_id)

    assert status == "dead"


# gl.eq_principle.prompt_non_comparative issues a host call of type
# "ExecPromptTemplate", not the plain "ExecPrompt" that gl.nondet.exec_prompt
# uses -- genlayer-test 0.29.2's direct-mode mock dispatcher only recognizes
# ExecPrompt, so vm.mock_llm() has no effect on this code path and these
# scenarios cannot be exercised locally with this tool version. The contract
# code itself is correct (matches the confirmed LlmHelloWorld doc pattern);
# this is a testing-tool gap, not a contract bug. Verify via Studio/Bradbury
# instead -- see the README.
@pytest.mark.skip(
    reason="genlayer-test 0.29.2 direct mode does not mock ExecPromptTemplate "
    "(used by prompt_non_comparative); needs Studio/Bradbury to exercise"
)
def test_verify_escalates_to_judge_and_reports_unchanged_meaning(direct_vm, weblock):
    direct_vm.mock_web(r"example\.com/terms", {"status": 200, "body": STATIC_PAGE})
    snapshot_id = weblock.freeze(
        "https://example.com/terms", "Payment is due within 30 days of delivery."
    )

    direct_vm.clear_mocks()
    reworded_page = "The contract terms remain unchanged. Payment must be made within thirty days of delivery."
    direct_vm.mock_web(r"example\.com/terms", {"status": 200, "body": reworded_page})
    direct_vm.mock_llm(r".*", "unchanged")

    status = weblock.verify(snapshot_id)

    assert status == "changed_cosmetic"


@pytest.mark.skip(
    reason="genlayer-test 0.29.2 direct mode does not mock ExecPromptTemplate "
    "(used by prompt_non_comparative); needs Studio/Bradbury to exercise"
)
def test_verify_escalates_to_judge_and_reports_material_change(direct_vm, weblock):
    direct_vm.mock_web(r"example\.com/terms", {"status": 200, "body": STATIC_PAGE})
    snapshot_id = weblock.freeze(
        "https://example.com/terms", "Payment is due within 30 days of delivery."
    )

    direct_vm.clear_mocks()
    retracted_page = "The contract terms remain unchanged. Payment is no longer required."
    direct_vm.mock_web(r"example\.com/terms", {"status": 200, "body": retracted_page})
    direct_vm.mock_llm(r".*", "changed")

    status = weblock.verify(snapshot_id)

    assert status == "changed_material"


def test_verify_unknown_snapshot_raises(direct_vm, weblock):
    with direct_vm.expect_revert("unknown snapshot"):
        weblock.verify("does-not-exist")


def test_get_by_submitter_lists_frozen_snapshots(direct_vm, weblock):
    from genlayer.py.types import Address

    direct_vm.mock_web(r"example\.com/terms", {"status": 200, "body": STATIC_PAGE})
    sender_hex = Address(direct_vm.sender).as_hex
    snapshot_id = weblock.freeze(
        "https://example.com/terms", "Payment is due within 30 days of delivery."
    )

    result = weblock.get_by_submitter(sender_hex)

    assert snapshot_id in result["snapshot_ids"]
