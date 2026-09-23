"""The Codex entry routes whole tasks without loading the Claude plugin surface."""
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def skill_documents(entry):
    """Follow shipped references as the reader would, checking portable links."""
    documents = {}
    pending = [entry]
    while pending:
        path = pending.pop()
        if path in documents:
            continue
        assert path.is_relative_to(entry.parent)
        documents[path] = path.read_text()
        for link in re.findall(r'\]\(([^)]+\.md)\)', documents[path]):
            reference = (path.parent / link).resolve()
            assert reference.is_file()
            pending.append(reference)
    return documents


def test_codex_has_one_standalone_entry_and_real_claude_routes():
    entries = sorted((ROOT / 'codex/skills').glob('*/SKILL.md'))
    assert len(entries) == 1
    text = entries[0].read_text()
    metadata = yaml.safe_load(text.split('---', 2)[1])
    assert metadata['name'] == 'quasi'
    assert not (ROOT / '.codex-plugin/plugin.json').exists()
    route_maps = [json.loads(block)
                  for document in skill_documents(entries[0]).values()
                  for block in re.findall(r'```json\n(.*?)\n```', document, re.S)
                  if 'cc_routes' in json.loads(block)]
    assert len(route_maps) == 1
    routes = route_maps[0]
    assert routes['topic_owner'] == 'codex'
    assert set(routes['cc_routes']) == {'paper', 'book', 'author', 'talk', 'translation', 'webpage', 'archive', 'draft'}
    for name in set(routes['cc_routes'].values()):
        path = ROOT / 'skills' / name / 'SKILL.md'
        assert yaml.safe_load(path.read_text().split('---', 2)[1])['name'] == name


def test_codex_entry_is_self_contained_skill_without_runtime_payload():
    entry = ROOT / 'codex/skills/quasi/SKILL.md'
    files = {p for p in entry.parent.rglob('*') if p.is_file()}
    assert all(p.suffix == '.md' for p in files)
    assert set(skill_documents(entry)) == files
