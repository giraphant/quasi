"""Topic producers must emit the same structure that disk admission observes."""
from copy import deepcopy

import pytest
import yaml
from pydantic import ValidationError

from scripts.schemas.contracts import artifact_contract_for_type
from scripts.schemas.topic import TopicSchema
from scripts.status.status import topic_status
from test_workflow_dispatch import _prepare, _prompt_request


@pytest.mark.parametrize('operation,role', [
    ('topic.steer', 'outline'),
    ('topic.webcard', 'card'),
    ('topic.synthesise.overview', 'overview'),
    ('topic.synthesise.resources', 'resources'),
])
def test_all_topic_writers_receive_canonical_artifact_contract(operation, role):
    request = _prompt_request(_prepare(operation)['prompt'])
    contract = request['artifact_contract']
    assert contract == artifact_contract_for_type('topic')
    assert request['output']['role'] == role
    schema = contract['frontmatter']['json_schema']
    assert schema['additionalProperties'] is False
    assert schema['properties']['type']['const'] == 'topic'
    assert set(schema['required']) == {'type', 'kind', 'title'}
    assert not {'research_key', 'topic_slug', 'query'} & set(schema['properties'])
    assert contract['document']['h1']
    assert contract['document']['evidence_rules']


def test_bts_checkpoint_metadata_and_sequential_disk_admissions(tmp_path):
    slug = 'iphone-repair-guides'
    talk = 'smartphone-metabolisms-material-flows-in-the-evolution-of-the-iphone-20250822'
    paper = 'barros-smartphone-repairability-indexes-2023'
    outline = tmp_path / f'vault/topics/{slug}/02-outline.md'
    outline.parent.mkdir(parents=True)
    subq = {
        'id': 'repair-protocol-comparison', 'question': 'Compare repair protocols',
        'coverage': 'thin', 'channel': 'mixed', 'theory_used': 1,
        'items': [{'kind': 'talk', 'slug': talk, 'role': 'theory'}], 'cards': [],
    }
    malformed = {
        'type': 'topic-outline', 'title': 'iPhone repair guides',
        'research_key': f'topic:{slug}', 'topic_slug': slug, 'query': 'Repair guides',
        'subquestions': [subq],
    }
    body = '\n# iPhone repair guides\n\nUser research notes remain intact.\n'

    def save(metadata):
        outline.write_text('---\n' + yaml.safe_dump(metadata) + '---\n' + body)

    save(malformed)
    with pytest.raises(ValidationError):
        TopicSchema.model_validate(malformed)
    invalid = topic_status(tmp_path, slug)
    assert invalid['facts']['outline']['usable'] is True
    assert invalid['facts']['outline']['projection'] is None
    for path in [f'vault/talks/{talk}/talk.md', f'vault/papers/{paper}.md']:
        product = tmp_path / path
        product.parent.mkdir(parents=True, exist_ok=True)
        product.write_text('---\ntitle: Existing material\n---\n# Existing material\n')

    repaired = {'type': 'topic', 'kind': 'outline', 'title': malformed['title'],
                'subquestions': deepcopy(malformed['subquestions'])}
    TopicSchema.model_validate(repaired)
    save(repaired)
    first = topic_status(tmp_path, slug)
    assert first['facts']['outline']['valid'] is True
    assert len(first['facts']['outline']['projection']['members']) == 1
    repaired['subquestions'][0]['items'].append({'kind': 'paper', 'slug': paper, 'role': 'method'})
    TopicSchema.model_validate(repaired)
    save(repaired)
    second = topic_status(tmp_path, slug)
    assert second != first
    members = second['facts']['outline']['projection']['members']
    assert [m['kind'] for m in members] == ['talk', 'paper']
    assert all(m['artifact']['usable'] for m in members)
    assert outline.read_text().endswith(body)
