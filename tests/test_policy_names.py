"""Canonical policy names agree across registration, YAML, persistence, UI, and docs."""

from __future__ import annotations

import ast
import re
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from conftest import toy_price
from tokenops.config.loader import DEFAULT_CONFIG, load_governance_yaml
from tokenops.control import build_governor, policies
from tokenops.control import config as config_module
from tokenops.control.config import POLICY_TEMPLATES, policy_template_ids
from tokenops.control.models import PolicyInstance
from tokenops.control.policies import tool_output_cap, trajectory_hint
from tokenops.control.store import Store
from tokenops.ui.policy_labels import policy_label

ROOT = Path(__file__).resolve().parents[1]
YAML_CONFIGS = sorted(
    [*DEFAULT_CONFIG.parent.glob("*.yaml"), *(ROOT / "examples/config").rglob("*.yaml")]
)


def test_registry_matches_policy_modules_exports_and_doc_slugs():
    module_ids = {
        path.stem
        for path in (ROOT / "src/tokenops/control/policies").glob("*.py")
        if not path.name.startswith("_")
    }
    doc_ids = {path.stem for path in (ROOT / "docs/policies").glob("*.md")}
    assert module_ids == doc_ids == set(POLICY_TEMPLATES)
    assert set(policies.__all__) == set(policy_template_ids())
    assert all(re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", name) for name in module_ids)
    assert len({template.display_name for template in POLICY_TEMPLATES.values()}) == len(
        POLICY_TEMPLATES
    )


@pytest.mark.parametrize("policy_id", policy_template_ids())
def test_template_key_matches_runtime_names_and_modules(policy_id):
    template = POLICY_TEMPLATES[policy_id]
    params = dict(template.default_params)
    if template.requires_budget:
        params["budget"] = "cap"
    governor = build_governor(
        {
            "budgets": [{"id": "cap", "limit_micros": 1_000_000}],
            "policies": {policy_id: params},
        },
        toy_price,
    )
    assert set(governor._policy_by_name) == {policy_id}
    [detector] = governor._detectors
    policy = governor._policy_by_name[policy_id]
    assert detector.name == policy.name == policy_id
    assert (
        type(detector).__module__
        == type(policy).__module__
        == (f"tokenops.control.policies.{policy_id}")
    )
    assert template.disabled_reason is None
    assert policy_label(policy_id) == f"{template.display_name} ({policy_id})"


@pytest.mark.parametrize("path", YAML_CONFIGS, ids=lambda path: str(path.relative_to(ROOT)))
def test_core_and_example_yaml_use_only_canonical_policy_keys(path):
    document = yaml.safe_load(path.read_text())
    assert isinstance(document, dict)
    if "governance" in document:
        governance = document["governance"]
        configured_ids = set(governance.get("policies") or {})
        assert configured_ids <= set(policy_template_ids())
        assert "has_hook" not in governance.get("policies", {}).get("context_compaction", {})
        governor = build_governor(governance, toy_price)
        assert set(governor._policy_by_name) == configured_ids


@pytest.mark.parametrize(
    ("filename", "registry", "k"),
    [("compose.yaml", ["search"], 3), ("triad.compose.yaml", ["search", "fetch"], 4)],
)
def test_compose_tool_policy_keeps_its_parameters_under_the_canonical_key(filename, registry, k):
    governance = load_governance_yaml(ROOT / "examples/config" / filename)
    assert "tool_reject" not in governance["policies"]
    assert governance["policies"]["tool_fix"] == {"registry": registry, "k": k}
    governor = build_governor(governance, toy_price)
    detector = next(detector for detector in governor._detectors if detector.name == "tool_fix")
    assert detector.registry == set(registry)
    assert detector.k == k


def test_default_seed_preserves_policy_keys_parameters_and_instance_ids(tmp_path, monkeypatch):
    monkeypatch.delenv("TOKENOPS_SKIP_GOVERNANCE_SEED", raising=False)
    governance = load_governance_yaml(DEFAULT_CONFIG)
    configured_ids = set(governance["policies"])
    assert configured_ids == set(policy_template_ids()) - {"time_budget"}
    store = Store(str(tmp_path / "seed.db"), auto_seed=False)
    try:
        assert store.seed_default_governance_if_empty(governance)
        instances = store.list_policy_instances()
        assert {instance.id for instance in instances} == {
            f"seed_{policy_id}" for policy_id in configured_ids
        }
        assert {instance.template for instance in instances} == configured_ids
        for instance in instances:
            original = governance["policies"][instance.template]
            assert instance.budget_id == original.get("budget")
            assert instance.params == {
                key: value for key, value in original.items() if key != "budget"
            }
        effective = store.governance_config_for("research")
        assert set(build_governor(effective, toy_price)._policy_by_name) == configured_ids
        assert not store.seed_default_governance_if_empty(governance)
    finally:
        store.close()


@pytest.mark.parametrize("instance_id", ["customer-policy-17", "seed_tool_fix", "cost_budget"])
def test_configurable_instance_id_does_not_rename_template(tmp_path, instance_id):
    store = Store(str(tmp_path / "instance.db"), auto_seed=False)
    try:
        instance = PolicyInstance(
            id=instance_id, template="step_cap", params={"max_steps": 7}, agent="research"
        )
        store.upsert_policy_instance(instance)
        assert store.get_policy_instance(instance_id) == instance
        effective = store.governance_config_for("research")
        assert set(effective["governance"]["policies"]) == {"step_cap"}
        assert set(build_governor(effective, toy_price)._policy_by_name) == {"step_cap"}
    finally:
        store.close()


@pytest.mark.parametrize(
    "unsupported",
    [
        "tool_freq",
        "tool_reject",
        "tool-fix",
        "Tool fix",
        "ToolFixDetector",
        "seed_tool_fix",
    ],
)
def test_unsupported_spellings_are_not_config_or_store_aliases(tmp_path, unsupported):
    with pytest.raises(ValueError, match="unknown policy"):
        build_governor({"policies": {unsupported: {}}}, toy_price)
    store = Store(str(tmp_path / "unsupported.db"), auto_seed=False)
    try:
        with pytest.raises(ValueError, match="unknown policy template"):
            store.upsert_policy_instance(PolicyInstance(id="custom-id", template=unsupported))
        assert store.list_policy_instances() == []
    finally:
        store.close()


@pytest.mark.parametrize("params", [{}, {"enabled": True}, {"enabled": False}])
def test_trajectory_hint_remains_known_but_unavailable(params):
    assert "trajectory_hint" in policy_template_ids(include_disabled=True)
    assert "trajectory_hint" not in policy_template_ids()
    assert POLICY_TEMPLATES["trajectory_hint"].factory is None
    assert "temporarily disabled" in policy_label("trajectory_hint")
    with pytest.raises(ValueError, match="trajectory_hint is temporarily disabled"):
        build_governor({"policies": {"trajectory_hint": params}}, toy_price)


def test_retained_trajectory_builder_keeps_its_canonical_name(tmp_path):
    store = Store(str(tmp_path / "trajectory-builder.db"), auto_seed=False)
    try:
        detector, policy = trajectory_hint.build(store, enabled=False)
        assert detector.name == policy.name == "trajectory_hint"
        assert type(detector).__module__ == type(policy).__module__ == trajectory_hint.__name__
    finally:
        store.close()


def test_disabled_stored_trajectory_instance_keeps_its_identity(tmp_path):
    store = Store(str(tmp_path / "trajectory.db"), auto_seed=False)
    try:
        instance = PolicyInstance(
            id="existing-trajectory-instance", template="trajectory_hint", enabled=False
        )
        store.upsert_policy_instance(instance)
        assert store.get_policy_instance(instance.id) == instance
        assert build_governor(store.governance_config_for("research"), toy_price)._detectors == []
        instance.enabled = True
        store.upsert_policy_instance(instance)
        with pytest.raises(ValueError, match="trajectory_hint is temporarily disabled"):
            build_governor(store.governance_config_for("research"), toy_price)
    finally:
        store.close()


def test_template_adapter_cannot_register_a_different_policy_name(monkeypatch):
    mismatched = replace(
        POLICY_TEMPLATES["step_cap"], factory=lambda params, ctx: tool_output_cap.build()
    )
    monkeypatch.setattr(
        config_module, "POLICY_TEMPLATES", {**POLICY_TEMPLATES, "step_cap": mismatched}
    )
    with pytest.raises(ValueError, match="both must match the config key"):
        build_governor({"policies": {"step_cap": {"max_steps": 1}}}, toy_price)


def test_glossary_labels_and_links_match_the_registry():
    index = ROOT / "docs/product/policies-index.md"
    glossary = index.read_text().split("## Canonical policy IDs\n", 1)[1].split("\n## ", 1)[0]
    rows = re.findall(
        r"^\| `(\w+)` \| ([^|]+) \| ([^|]+) \| \[([^\]]+)\]\(([^)]+)\) \|$",
        glossary,
        re.MULTILINE,
    )
    assert len(rows) == len(POLICY_TEMPLATES)
    assert {row[0] for row in rows} == set(POLICY_TEMPLATES)
    seeded_ids = set(load_governance_yaml(DEFAULT_CONFIG)["policies"])
    for policy_id, display_name, availability, link_text, target in rows:
        template = POLICY_TEMPLATES[policy_id]
        assert display_name == template.display_name
        assert link_text == f"{policy_id}.md"
        doc = (index.parent / target).resolve()
        assert doc == ROOT / f"docs/policies/{policy_id}.md"
        assert doc.read_text().splitlines()[0].startswith(f"# {template.display_name}")
        if template.factory is None:
            assert availability == "Temporarily disabled"
        else:
            assert availability == ("In default seed" if policy_id in seeded_ids else "Opt-in")


def test_context_compaction_admin_defaults_do_not_reintroduce_removed_capability_flag():
    assert POLICY_TEMPLATES["context_compaction"].default_params == {"ctx_max": 100000}


def test_time_budget_is_available_without_being_seeded(tmp_path):
    assert "time_budget" in policy_template_ids()
    assert "time_budget" not in load_governance_yaml(DEFAULT_CONFIG)["policies"]
    store = Store(str(tmp_path / "time-budget.db"), auto_seed=False)
    try:
        instance = PolicyInstance(
            id="customer-latency-limit", template="time_budget", params={"max_seconds": 2.0}
        )
        store.upsert_policy_instance(instance)
        governor = build_governor(store.governance_config_for("research"), toy_price)
        assert store.get_policy_instance(instance.id) == instance
        assert set(governor._policy_by_name) == {"time_budget"}
        assert governor._detectors[0].max_seconds == 2.0
    finally:
        store.close()


def test_demo_capture_points_at_canonical_policy_registration():
    script = ast.parse((ROOT / "scripts/capture_demo_media.py").read_text())
    assignment = next(
        node
        for node in script.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "CODE_SNIPPETS" for target in node.targets
        )
    )
    snippets = ast.literal_eval(assignment.value)
    snippet = next(item for item in snippets if item["name"] == "04_governor_setup")
    source = (ROOT / snippet["file"]).read_text().splitlines()
    assert source[snippet["start"] - 1].strip() == 'gov_cfg = config.get("governance", config)'
    assert source[snippet["end"] - 1].strip() == "return governor"
    captured = "\n".join(source[snippet["start"] - 1 : snippet["end"]])
    assert "template = POLICY_TEMPLATES.get(name)" in captured
    assert "detector, policy = template.factory(params or {}, ctx)" in captured
    assert "governor.register(detector, policy)" in captured
    assert all(snippet["start"] <= line <= snippet["end"] for line in snippet["highlight"])


@pytest.mark.parametrize("name", ["custom_policy", "tool_freq", "historical-unknown"])
def test_unknown_display_ids_remain_verbatim(name):
    assert policy_label(name) == name
