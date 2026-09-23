"""The Codex entry routes whole tasks without loading the Claude plugin surface."""
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_codex_has_one_standalone_entry_and_real_claude_routes():
    entries = sorted((ROOT / 'codex/skills').glob('*/SKILL.md'))
    assert len(entries) == 1
    text = entries[0].read_text()
    metadata = yaml.safe_load(text.split('---', 2)[1])
    assert metadata['name'] == 'quasi'
    assert not (ROOT / '.codex-plugin/plugin.json').exists()
    routes = next(json.loads(block) for block in re.findall(r'```json\n(.*?)\n```', text, re.S))
    assert routes['topic_owner'] == 'codex'
    assert set(routes['cc_routes']) == {'paper', 'book', 'author', 'talk', 'translation', 'webpage', 'archive', 'draft'}
    for name in set(routes['cc_routes'].values()):
        path = ROOT / 'skills' / name / 'SKILL.md'
        assert yaml.safe_load(path.read_text().split('---', 2)[1])['name'] == name
    assert (entries[0].parent / 'references/cc-task.md').is_file()


def test_codex_entry_is_self_contained_skill_without_runtime_payload():
    files = {p.relative_to(ROOT / 'codex/skills/quasi').as_posix()
             for p in (ROOT / 'codex/skills/quasi').rglob('*') if p.is_file()}
    assert files == {'SKILL.md', 'references/cc-task.md'}
