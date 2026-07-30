from __future__ import annotations

import json
from pathlib import Path
from queue import Empty, Queue
import shutil
import subprocess
from threading import Thread

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DRIVER = PLUGIN_ROOT / "scripts" / "codex-driver.mjs"
SMOKE = PLUGIN_ROOT / "tests" / "fixtures" / "codex-smoke.mjs"


def node() -> str:
    command = shutil.which("node")
    if not command:
        pytest.skip("node not on PATH")
    return command


def test_codex_driver_help() -> None:
    result = subprocess.run(
        [node(), str(DRIVER), "--help"],
        cwd=PLUGIN_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.startswith("Usage: quasi-codex-driver ")
    assert "--args-file" in result.stdout
    assert result.stderr == ""


class Driver:
    def __init__(self, script: Path, cwd: Path):
        self.process = subprocess.Popen(
            [
                node(),
                str(DRIVER),
                "--plugin-root",
                str(PLUGIN_ROOT),
                "--script",
                str(script),
                "--cwd",
                str(cwd),
                "--args-json",
                "{}",
                "--timeout-ms",
                "5000",
            ],
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.events: Queue[dict] = Queue()
        self.reader = Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self) -> None:
        assert self.process.stdout
        for line in self.process.stdout:
            self.events.put(json.loads(line))

    def next(self, event_type: str) -> dict:
        skipped: list[dict] = []
        try:
            while True:
                event = self.events.get(timeout=5)
                if event.get("type") == event_type:
                    return event
                skipped.append(event)
        except Empty as error:
            stderr = self.process.stderr.read() if self.process.poll() is not None else ""
            raise AssertionError(
                f"timed out waiting for {event_type}; skipped={skipped}; stderr={stderr}"
            ) from error

    def send(self, event: dict) -> None:
        assert self.process.stdin
        self.process.stdin.write(json.dumps(event) + "\n")
        self.process.stdin.flush()

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait(timeout=5)


def test_codex_driver_requests_visible_agent_and_validates_receipt(
    tmp_path: Path,
) -> None:
    driver = Driver(SMOKE, tmp_path)
    try:
        ready = driver.next("ready")
        assert ready["protocol"] == "quasi-codex-driver/1"
        assert ready["concurrency"] == 3

        request = driver.next("agent_request")
        assert request["agent_type"] == "general-purpose"
        assert request["codex_agent_type"] == "worker"
        assert request["label"] == "codex-smoke"
        request_path = Path(request["request_path"])
        receipt_path = Path(request["receipt_path"])
        envelope = json.loads(request_path.read_text(encoding="utf-8"))
        assert envelope["id"] == request["id"]
        assert envelope["codex_agent_type"] == "worker"
        assert envelope["receipt_path"] == str(receipt_path)
        assert envelope["plugin_root"] == str(PLUGIN_ROOT)
        assert envelope["project_cwd"] == str(tmp_path)
        assert "Do not spawn subagents" not in envelope["instructions"]
        assert envelope["prompt"].startswith("Return a JSON receipt")
        assert envelope["schema"]["required"] == ["status", "runtime"]

        driver.send(
            {
                "type": "agent_result",
                "id": request["id"],
                "result": {"status": "wrong", "runtime": "codex"},
            }
        )
        rejected = driver.next("receipt_rejected")
        assert rejected["id"] == request["id"]
        assert "must be one of" in rejected["error"]

        note = "diagnostic-" + ("x" * 5000)
        receipt_path.write_text(
            json.dumps({"status": "ok", "runtime": "codex", "note": note}),
            encoding="utf-8",
        )
        driver.send(
            {
                "type": "agent_result",
                "id": request["id"],
                "result_path": str(receipt_path),
            }
        )
        result = driver.next("result")
        assert result["result"] == {
            "status": "ok",
            "runtime": "codex",
            "note": note,
        }
        assert driver.process.wait(timeout=5) == 0
        assert not request_path.exists()
        assert not receipt_path.exists()
    finally:
        driver.close()


def test_codex_driver_rejects_const_and_additional_properties(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / "strict-receipt.mjs"
    workflow.write_text(
        """
export const meta = { name: 'strict-receipt' }
return agent('strict receipt', {
  agentType: 'general-purpose',
  label: 'strict-receipt',
  schema: {
    type: 'object',
    additionalProperties: false,
    required: ['status', 'nested'],
    properties: {
      status: { const: 'ok' },
      nested: {
        type: 'object',
        additionalProperties: false,
        required: ['key'],
        properties: { key: { const: 'fixed' } },
      },
    },
  },
})
""",
        encoding="utf-8",
    )
    driver = Driver(workflow, tmp_path)
    try:
        driver.next("ready")
        request = driver.next("agent_request")
        driver.send(
            {
                "type": "agent_result",
                "id": request["id"],
                "result": {"status": "wrong", "nested": {"key": "fixed"}},
            }
        )
        rejected = driver.next("receipt_rejected")
        assert "must equal" in rejected["error"]

        driver.send(
            {
                "type": "agent_result",
                "id": request["id"],
                "result": {
                    "status": "ok",
                    "nested": {"key": "fixed", "extra": True},
                },
            }
        )
        rejected = driver.next("receipt_rejected")
        assert "extra is not allowed" in rejected["error"]

        driver.send(
            {
                "type": "agent_result",
                "id": request["id"],
                "result": {"status": "ok", "nested": {"key": "fixed"}},
            }
        )
        assert driver.next("result")["result"]["status"] == "ok"
        assert driver.process.wait(timeout=5) == 0
    finally:
        driver.close()


def test_codex_driver_parallel_requests_can_finish_out_of_order(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / "parallel.mjs"
    workflow.write_text(
        """
export const meta = { name: 'parallel-smoke' }
return parallel([
  () => agent('first', { agentType: 'general-purpose', label: 'first' }),
  () => agent('second', { agentType: 'general-purpose', label: 'second' }),
])
""",
        encoding="utf-8",
    )
    driver = Driver(workflow, tmp_path)
    try:
        driver.next("ready")
        requests = [driver.next("agent_request"), driver.next("agent_request")]
        by_label = {request["label"]: request for request in requests}

        driver.send(
            {
                "type": "agent_result",
                "id": by_label["second"]["id"],
                "result": "two",
            }
        )
        driver.send(
            {
                "type": "agent_result",
                "id": by_label["first"]["id"],
                "result": "one",
            }
        )

        assert driver.next("result")["result"] == ["one", "two"]
        assert driver.process.wait(timeout=5) == 0
    finally:
        driver.close()


def test_codex_driver_maps_quasi_agent_names_to_registered_codex_roles(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / "native-role.mjs"
    workflow.write_text(
        """
export const meta = { name: 'native-role-smoke' }
return agent('download one paper', {
  agentType: 'quasi:download-agent',
  label: 'download:paper-slug',
})
""",
        encoding="utf-8",
    )
    driver = Driver(workflow, tmp_path)
    try:
        driver.next("ready")
        request = driver.next("agent_request")
        assert request["agent_type"] == "quasi:download-agent"
        assert request["codex_agent_type"] == "quasi_download"
        envelope = json.loads(
            Path(request["request_path"]).read_text(encoding="utf-8")
        )
        assert envelope["codex_agent_type"] == "quasi_download"

        driver.send(
            {"type": "agent_result", "id": request["id"], "result": "done"}
        )
        assert driver.next("result")["result"] == "done"
    finally:
        driver.close()
