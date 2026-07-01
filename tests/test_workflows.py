"""Workflow DSL tests: validation, topological ordering, and submission."""

from pathlib import Path

import pytest

from mco.orchestrator.workflows import (
    WorkflowError,
    load_workflow,
    submit_workflow,
    topo_order,
)


VALID_YAML = """
name: release-pipeline
steps:
  - id: research
    role: claude
    title: Research
    instructions: Look things up.
  - id: build
    role: codex
    title: Build
    instructions: Implement it.
    depends_on: [research]
    max_retries: 2
    escalate_to_role: human
  - id: ship
    role: codex
    title: Ship
    instructions: Publish.
    depends_on: [build]
    requires_approval: true
"""


class FakeClient:
    """Records send() calls and hands back sequential job ids."""

    def __init__(self, fail_on_title=None):
        self.calls = []
        self._n = 0
        self._fail_on_title = fail_on_title

    def send(self, to_role, title, instructions, to_instance=None, depends_on=None,
             requires_approval=False, max_retries=0, escalate_to_role=None,
             extra_payload=None):
        self.calls.append({
            "to_role": to_role, "title": title, "depends_on": depends_on or [],
            "requires_approval": requires_approval, "max_retries": max_retries,
            "escalate_to_role": escalate_to_role, "extra_payload": extra_payload,
        })
        if self._fail_on_title and self._fail_on_title in title:
            return {"success": False}
        self._n += 1
        return {"success": True, "job": {"id": f"job-{self._n}"}}


class TestLoadWorkflow:
    def test_valid_yaml_loads(self):
        wf = load_workflow(VALID_YAML)
        assert wf["name"] == "release-pipeline"
        assert len(wf["steps"]) == 3

    def test_missing_name_rejected(self):
        with pytest.raises(WorkflowError, match="name"):
            load_workflow("steps:\n  - id: a\n    role: codex\n    title: t\n")

    def test_empty_steps_rejected(self):
        with pytest.raises(WorkflowError, match="steps"):
            load_workflow("name: x\nsteps: []\n")

    def test_string_source_never_reads_the_filesystem(self, tmp_path, monkeypatch):
        """Security regression: a bare str must always be parsed as literal YAML
        text, never guessed at as a path — POST /api/workflows only requires
        jobs:write (a worker-level scope), so implicit path resolution here
        would be an arbitrary-file-read primitive for any registered agent."""
        monkeypatch.chdir(tmp_path)
        secret = tmp_path / "name"  # a no-newline source could collide with this
        secret.write_text("TOP SECRET FILE CONTENT", encoding="utf-8")
        # A short, no-newline string that happens to equal an existing filename:
        # must be parsed as YAML (and fail as invalid YAML/shape), never opened.
        with pytest.raises(WorkflowError):
            load_workflow("name")

    def test_path_object_still_loads_from_disk(self, tmp_path):
        """CLI callers (mco workflow <file>) opt in explicitly with Path(...)."""
        p = tmp_path / "wf.yaml"
        p.write_text(VALID_YAML, encoding="utf-8")
        wf = load_workflow(p)
        assert wf["name"] == "release-pipeline"

    def test_missing_path_object_raises_workflow_error(self, tmp_path):
        with pytest.raises(WorkflowError, match="not found"):
            load_workflow(tmp_path / "does-not-exist.yaml")

    def test_duplicate_step_id_rejected(self):
        with pytest.raises(WorkflowError, match="Duplicate"):
            load_workflow({"name": "x", "steps": [
                {"id": "a", "role": "codex", "title": "t"},
                {"id": "a", "role": "codex", "title": "t"},
            ]})

    def test_unknown_dependency_rejected(self):
        with pytest.raises(WorkflowError, match="unknown step"):
            load_workflow({"name": "x", "steps": [
                {"id": "a", "role": "codex", "title": "t", "depends_on": ["ghost"]},
            ]})

    def test_cycle_rejected(self):
        with pytest.raises(WorkflowError, match="cycle"):
            load_workflow({"name": "x", "steps": [
                {"id": "a", "role": "codex", "title": "t", "depends_on": ["b"]},
                {"id": "b", "role": "codex", "title": "t", "depends_on": ["a"]},
            ]})

    def test_step_without_role_rejected(self):
        with pytest.raises(WorkflowError, match="role"):
            load_workflow({"name": "x", "steps": [{"id": "a", "title": "t"}]})


class TestTopoOrder:
    def test_dependencies_come_first(self):
        wf = load_workflow(VALID_YAML)
        ordered = [s["id"] for s in topo_order(wf["steps"])]
        assert ordered.index("research") < ordered.index("build") < ordered.index("ship")


class TestSubmitWorkflow:
    def test_steps_become_jobs_with_translated_deps(self):
        client = FakeClient()
        job_ids = submit_workflow(client, load_workflow(VALID_YAML))
        assert set(job_ids) == {"research", "build", "ship"}

        build_call = next(c for c in client.calls if c["title"] == "Build")
        assert build_call["depends_on"] == [job_ids["research"]]
        assert build_call["max_retries"] == 2
        assert build_call["escalate_to_role"] == "human"

        ship_call = next(c for c in client.calls if c["title"] == "Ship")
        assert ship_call["depends_on"] == [job_ids["build"]]
        assert ship_call["requires_approval"] is True

    def test_every_step_stamped_with_one_workflow_run(self):
        """Context Exchange threading: all steps share a run id so each
        downstream step deterministically receives its predecessors' handoffs."""
        client = FakeClient()
        submit_workflow(client, load_workflow(VALID_YAML))
        stamps = [c["extra_payload"]["workflow"] for c in client.calls]
        assert all(s["name"] == "release-pipeline" for s in stamps)
        run_ids = {s["run"] for s in stamps}
        assert len(run_ids) == 1 and run_ids != {None}
        assert {s["step"] for s in stamps} == {"research", "build", "ship"}

    def test_failed_step_raises_with_progress(self):
        client = FakeClient(fail_on_title="Build")
        with pytest.raises(WorkflowError, match="build"):
            submit_workflow(client, load_workflow(VALID_YAML))
