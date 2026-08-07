from __future__ import annotations

import tomllib
import xml.etree.ElementTree as ElementTree
from pathlib import Path

_ROOT = Path(__file__).parents[1]
_WORKFLOW_PATH = _ROOT / ".github" / "workflows" / "release.yml"
_SPEC_PATH = _ROOT / "packaging" / "telemetry_reporter.spec"
_APPLICATION_CONFIG_PATH = _ROOT / "packaging" / "release" / "Telemetry Reporter.exe.config"


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
    marked_tests = workflow.index("- name: Run Mark-of-the-Web packaged tests")
    archive = workflow.index("- name: Create ZIP and checksum")
    artifact_upload = workflow.index("- name: Upload workflow artifacts")
    publication = workflow.index("- name: Publish release after successful validation")
    assert quality_gate < packaged_tests < marked_tests < archive < artifact_upload < publication


def test_portable_bundle_includes_remote_source_application_config() -> None:
    root = ElementTree.parse(_APPLICATION_CONFIG_PATH).getroot()
    setting = root.find("./runtime/loadFromRemoteSources")

    assert setting is not None
    assert setting.attrib == {"enabled": "true"}

    specification = _SPEC_PATH.read_text(encoding="utf-8")
    workflow = _workflow_text()
    assert 'repository_root / "packaging" / "release" / "Telemetry Reporter.exe.config"' in (
        specification
    )
    assert 'bundle_root / "Telemetry Reporter.exe.config"' in specification
    assert '@("LICENSE", "README.txt", "Telemetry Reporter.exe.config")' in workflow
    assert "Packaged application configuration is not valid XML" in workflow
    assert "must enable loadFromRemoteSources" in workflow


def test_release_workflow_exercises_marked_managed_assemblies() -> None:
    workflow = _workflow_text()

    assert "-Stream Zone.Identifier" in workflow
    assert "ZoneId=3" in workflow
    assert '"_internal\\pythonnet\\runtime\\Python.Runtime.dll"' in workflow
    assert 'Invoke-MarkedPackagedTest "--self-test"' in workflow
    assert 'Invoke-MarkedPackagedTest "--ui-smoke-test"' in workflow
    assert "Marked packaged diagnostics left browser logs outside temporary storage" in workflow


def test_release_workflow_rejects_browser_logs_outside_temporary_storage() -> None:
    workflow = _workflow_text()

    assert "-WorkingDirectory $smokeDirectory" in workflow
    assert 'Join-Path $smokeDirectory "debug.log"' in workflow
    assert '"dist\\Telemetry Reporter\\debug.log"' in workflow
    assert "left browser logs outside temporary storage" in workflow


def test_current_package_version_has_committed_release_notes() -> None:
    pyproject = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]

    notes_path = _ROOT / "packaging" / "release" / "notes" / f"v{version}.md"
    assert notes_path.is_file()
