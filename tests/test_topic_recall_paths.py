"""BTS recall regression: absolute read paths must not escape into receipts."""
import re

import pytest

from test_workflow_dispatch import _dispatch, _invocation, _prepare, _prompt_request
from test_topic_plan import topic_input, recall_complete
from workflow_test_support import run_generated_workflow

SLUG = 'smartphone-metabolisms-material-flows-in-the-evolution-of-the-iphone-20250822'
PATH = f'vault/talks/{SLUG}/talk.md'


@pytest.mark.parametrize('path,accepted', [
    (PATH, True),
    ('vault/papers/barros-smartphone-repairability-indexes-2023.md', True),
    ('vault/books/perzanowski-the-right-to-repair-2022/00-overview.md', True),
    ('/Users/ramudai/Documents/Learn/bts/' + PATH, False),
    ('./' + PATH, False),
    ('file:///' + PATH, False),
    ('vault/talks/../outside/talk.md', False),
    (PATH.replace('/', '\\'), False),
])
def test_recall_schema_excludes_noncanonical_path_spellings(path, accepted):
    prepared = _prepare('topic.recall')
    schema = prepared['options']['schema']['properties']['items']['items']['properties']['path']
    assert 'null' in schema['type']
    assert bool(re.fullmatch(schema['pattern'], path)) is accepted
    request = _prompt_request(prepared['prompt'])
    assert request['path_contract']['representation'] == 'project_relative'
    assert request['path_contract']['canonical']['talk'] == 'vault/talks/{slug}/talk.md'


@pytest.mark.parametrize('items,accepted', [
    ([{'kind': 'talk', 'slug': SLUG, 'path': PATH}], True),
    ([{'kind': 'talk', 'slug': SLUG, 'path': None}], True),
    ([{'kind': 'talk', 'slug': SLUG, 'path': 'vault/talks/other-talk/talk.md'}], False),
    ([{'kind': 'paper', 'slug': SLUG, 'path': PATH}], False),
    ([{'kind': 'talk', 'slug': SLUG, 'path': PATH}] * 2, False),
    ([{'kind': 'talk', 'slug': SLUG, 'path': '/Users/ramudai/Documents/Learn/bts/' + PATH}], False),
])
def test_recall_keeps_exact_join_and_duplicate_checks(items, accepted):
    report = _dispatch({'invocation': _invocation('topic.recall'), 'model_output': recall_complete(items)})
    assert report['agentCalls'] == 1
    assert report['result']['kind'] == ('receipt' if accepted else 'incoherent_complete')


def test_generated_topic_accepts_bts_talk_candidate_and_requests_observation():
    result = run_generated_workflow('topic', topic_input(), [recall_complete([
        {'kind': 'talk', 'slug': SLUG, 'path': PATH},
    ])])
    assert result['agentCalls'] == 1
    assert result['value']['terminal'] == 'needs_observation'
    assert result['value']['routes'] == [{'kind': 'talk', 'slug': SLUG}]
