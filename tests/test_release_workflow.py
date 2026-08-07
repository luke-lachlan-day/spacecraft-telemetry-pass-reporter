from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).parents[1]
_WORKFLOW_PATH = _ROOT / ".github" / "workflows" / "release.yml"


def _workflow_text() -> str:
    return _WORKFLOW_PATH.read_text(encoding="utf-8")


def test_release_workflow_publishes_only_from_version_tags() -> None:
    workflow = _workflow_text()

    assert 'tags: ["v*"]' in workflow
    assert "workflow_dispatch:" in workflow
    assert "types: [published]" not in workflow
    assert "if: github.ref_type == 'tag'" in workflow
    assert "if: github.event_name == 'workflow_dispatch'" not in workflow


def test_release_workflow_validates_metadata_before_atomic_publication() -> None:
    workflow = _workflow_text()

    assert "$env:GITHUB_REF_NAME -ne $expectedTag" in workflow
    assert "Release notes are missing" in workflow
    assert 'gh release create "$env:RELEASE_TAG"' in workflow
    assert "gh release upload" not in workflow
    assert "--verify-tag" in workflow
    assert "--notes-file" in workflow

    quality_gate = workflow.index("needs: quality-gate")
    packaged_tests = workflow.index("- name: Run packaged self-tests")
    archive = workflow.index("- name: Create ZIP and checksum")
    artifact_upload = workflow.index("- name: Upload workflow artifacts")
    publication = workflow.index("- name: Publish release after successful validation")
    assert quality_gate < packaged_tests < archive < artifact_upload < publication


def test_release_workflow_rejects_browser_logs_outside_temporary_storage() -> None:
    workflow = _workflow_text()

    assert "-WorkingDirectory $smokeDirectory" in workflow
    assert 'Join-Path $smokeDirectory "debug.log"' in workflow
    assert '"dist\\Telemetry Reporter\\debug.log"' in workflow
    assert "left browser logs outside temporary storage" in workflow
