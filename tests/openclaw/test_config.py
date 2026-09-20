from pathlib import Path

import pytest

from smolagents.openclaw import OpenClawConfig, load_config
from smolagents.openclaw.config import _parse_yaml
from smolagents.openclaw.niches import DEFAULT_NICHES


def test_default_config_uses_curated_niches():
    cfg = OpenClawConfig()
    assert len(cfg.niches) == 10
    assert cfg.model.type == "mock"
    assert cfg.memory_path == ":memory:"


def test_load_config_from_inline_yaml_string():
    yaml_text = """
memory_path: /tmp/foo.db
seed: 99
max_steps_per_day: 6
model:
  type: mock
  model_id: stub
"""
    cfg = load_config(yaml_text)
    assert cfg.memory_path == "/tmp/foo.db"
    assert cfg.seed == 99
    assert cfg.max_steps_per_day == 6
    assert cfg.model.model_id == "stub"
    assert len(cfg.niches) == 10


def test_load_config_from_file(tmp_path: Path):
    p = tmp_path / "openclaw.yaml"
    p.write_text("memory_path: ./db.sqlite\nseed: 1\n")
    cfg = load_config(p)
    assert cfg.memory_path == "./db.sqlite"
    assert cfg.seed == 1


def test_niche_overrides_patch_curated_baselines():
    yaml_text = """
niches:
  - slug: outdoor_gear
    base_traffic: 9000
    volatility: 0.05
"""
    cfg = load_config(yaml_text)
    assert len(cfg.niches) == 1
    n = cfg.niches[0]
    assert n.slug == "outdoor_gear"
    assert n.base_traffic == 9000
    assert n.volatility == 0.05
    # Untouched fields preserve the curated default values.
    base = next(d for d in DEFAULT_NICHES if d.slug == "outdoor_gear")
    assert n.base_aov == base.base_aov
    assert n.affiliate_programs == base.affiliate_programs


def test_unknown_slug_requires_full_definition():
    with pytest.raises(ValueError, match="missing required fields"):
        load_config("niches:\n  - slug: brand_new_niche\n")


def test_unknown_model_type_raises_at_factory_build_time():
    cfg = load_config("model:\n  type: nope\n")
    from smolagents.openclaw.orchestrator import build_model_factory
    with pytest.raises(ValueError, match="Unknown model type"):
        build_model_factory(cfg.model)


def test_yaml_parser_handles_comments_and_inline_lists():
    parsed = _parse_yaml(
        """
# top comment
key: value  # trailing comment
nums: [1, 2, 3]
nested:
  a: 1
  b: "two"
list:
  - x: 1
    y: 2
  - x: 3
    y: 4
"""
    )
    assert parsed["key"] == "value"
    assert parsed["nums"] == [1, 2, 3]
    assert parsed["nested"] == {"a": 1, "b": "two"}
    assert parsed["list"] == [{"x": 1, "y": 2}, {"x": 3, "y": 4}]


def test_dict_source_is_passed_through():
    cfg = load_config({"memory_path": "/x", "seed": 7})
    assert cfg.memory_path == "/x"
    assert cfg.seed == 7
