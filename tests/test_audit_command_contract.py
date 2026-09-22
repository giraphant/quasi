"""Audit producers receive the executable writer interface, not report flags."""
import pytest
from test_workflow_dispatch import _prepare, _prompt_request


@pytest.mark.parametrize("operation", ["archive.audit", "paper.audit"])
def test_audit_request_names_the_writer_command_without_report_flags(operation):
    request = _prompt_request(_prepare(operation)["prompt"])
    assert request["audit_command"]["argv"] == ["quasi-audit", "--path", request["target"]["path"]]
