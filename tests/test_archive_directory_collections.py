"""Archive directory collections preserve identity, exact routes and acquisition."""
import fcntl
import json
import multiprocessing
from pathlib import Path
import shutil

import pytest

from scripts.archive import archive as archive_cli
from scripts.archive.archive import collect
from scripts.archive.inventory import digest, revision
from scripts.archive.paths import archive_pages, archive_path
from scripts.core import read_frontmatter
from scripts.schemas.topic import TopicSchema
from scripts.status.status import archive_status, scan_status, topic_status
from scripts.vault.resolve import resolve
from test_archive_collection import asset, request, SLUG, URL
from test_archive_plan import archive_input, COMPLETE
from test_material_plans import audit_complete
from workflow_test_support import run_generated_workflow


def grouped(root):
    value = request(root)
    assert collect(root, value)['status'] == 'complete'
    group = root / 'vault/archives/维修 材料'
    group.mkdir()
    (group / 'collection.md').write_text('# 维修材料\n')
    source = root / 'vault/archives' / SLUG
    destination = group / SLUG
    source.rename(destination)
    return destination, value


def test_grouped_status_resolve_and_recollect_without_duplicate(tmp_path):
    directory, stale = grouped(tmp_path)
    observed = archive_status(tmp_path, SLUG)
    assert observed['facts']['canonical']['path'] == (directory / 'archive.md').relative_to(tmp_path).as_posix()
    assert observed['facts']['canonical']['usable']
    assert archive_path(tmp_path, SLUG) == directory / 'archive.md'
    row = resolve(tmp_path, [{'kind': 'archive', 'slug': 'another-name', 'url': URL}])['resolved'][0]
    assert row['path'] == observed['facts']['canonical']['path']
    assert row['vault_slug'] == SLUG
    assert collect(tmp_path, stale)['status'] == 'blocked'  # moving invalidates old testimony
    fresh = {**stale, 'expected_revision': observed['facts']['collection']['revision'], 'topics': ['new-topic']}
    assert collect(tmp_path, fresh)['status'] == 'complete'
    assert 'new-topic' in read_frontmatter(directory / 'archive.md').frontmatter['topics']
    assert not (tmp_path / 'vault/archives' / SLUG).exists()
    assert len(archive_pages(tmp_path)) == 1


def test_duplicate_slugs_block_and_unmarked_folders_do_not_group(tmp_path):
    directory, value = grouped(tmp_path)
    shutil.copytree(directory, tmp_path / 'vault/archives' / SLUG)
    with pytest.raises(ValueError, match='duplicate'):
        archive_path(tmp_path, SLUG)
    assert not archive_status(tmp_path, SLUG)['facts']['canonical']['usable']
    assert resolve(tmp_path, [{'kind': 'archive', 'slug': SLUG, 'url': URL}])['resolved'][0]['error']
    shutil.rmtree(tmp_path / 'vault/archives' / SLUG)
    (directory.parent / 'collection.md').unlink()
    assert archive_pages(tmp_path) == []


def test_collector_respects_marple_exclusive_move_lock(tmp_path):
    directory, value = grouped(tmp_path)
    value['expected_revision'] = revision(tmp_path, directory)
    with (tmp_path / '.marple/archive-collections.lock').open('r+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = collect(tmp_path, value)
        assert result['status'] == 'blocked', result


def test_workflow_uses_observed_grouped_paths():
    value = archive_input(usable=True, topics=['older-topic'])
    facts = value['observation']['facts']
    old = facts['canonical']['path'].removesuffix('/archive.md')
    new = old.replace('vault/archives/', 'vault/archives/维修 材料/')
    facts['canonical']['path'] = new + '/archive.md'
    facts['collection']['path'] = new + '/manifest.yaml'
    result = run_generated_workflow('archive', value, [COMPLETE], capture_agent_requests=True)
    assert result['value']['terminal'] == 'needs_observation', result
    assert result['agentCalls'] == 1
    from test_workflow_dispatch import _prompt_request
    envelope = _prompt_request(result['agentRequests'][0]['prompt'])
    assert envelope['exact_output'] == new + '/archive.md'
    assert envelope['exact_manifest'] == new + '/manifest.yaml'
    assert envelope['originals_directory'] == new + '/originals'


def test_collector_stops_for_pending_marple_operation(tmp_path):
    directory, value = grouped(tmp_path)
    value['expected_revision'] = revision(tmp_path, directory)
    operations = tmp_path / '.marple/collection-operations'
    operations.mkdir()
    (operations / 'pending.json').write_text(json.dumps({'command': {'action': 'move'}}))
    assert collect(tmp_path, value)['status'] == 'blocked'
    (operations / 'pending.json').write_text(json.dumps({'result': {'dryRun': False}}))
    assert collect(tmp_path, value)['status'] == 'complete'


@pytest.mark.parametrize('journal', ['null', '[]', '42', '"pending"', '{', '{}', '{"result":null}'])
def test_invalid_or_unfinished_journal_blocks_without_writes(tmp_path, journal):
    directory, value = grouped(tmp_path)
    value['expected_revision'] = revision(tmp_path, directory)
    operations = tmp_path / '.marple/collection-operations'
    operations.mkdir()
    (operations / 'pending.json').write_text(journal)
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    result = collect(tmp_path, value)
    assert result['status'] == 'blocked', result
    assert result['code'] == 'archive.conflict'
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before


@pytest.mark.parametrize('invalid', ['ambiguous', 'nested', 'group_symlink', 'member_symlink',
                                     'marker_symlink', 'unsafe_name'])
def test_invalid_collection_layout_never_admits_or_writes(tmp_path, invalid):
    directory, value = grouped(tmp_path)
    group = directory.parent
    if invalid == 'ambiguous':
        (group / 'archive.md').write_bytes((directory / 'archive.md').read_bytes())
    elif invalid == 'nested':
        (directory / 'collection.md').write_text('')
    elif invalid in ('group_symlink', 'member_symlink'):
        target = group if invalid == 'group_symlink' else directory
        saved = tmp_path / 'saved'
        target.rename(saved)
        target.symlink_to(saved, target_is_directory=True)
    elif invalid == 'marker_symlink':
        (group / 'collection.md').unlink()
        (group / 'collection.md').symlink_to(directory / 'archive.md')
    else:
        group.rename(group.with_name('bad\\name'))
    with pytest.raises(ValueError):
        archive_path(tmp_path, SLUG)
    assert scan_status(tmp_path)['items'] == []
    assert not archive_status(tmp_path, SLUG)['facts']['canonical']['usable']
    assert resolve(tmp_path, [{'kind': 'archive', 'slug': SLUG, 'url': URL}])['resolved'][0]['error']
    assert collect(tmp_path, value)['status'] in ('blocked', 'failed')
    assert not (tmp_path / 'vault/archives' / SLUG).exists()


def test_existing_collection_name_cannot_become_an_archive(tmp_path):
    group = tmp_path / 'vault/archives' / SLUG
    group.mkdir(parents=True)
    (group / 'collection.md').write_text('')
    with pytest.raises(ValueError, match='occupied'):
        archive_path(tmp_path, SLUG)
    assert collect(tmp_path, request(tmp_path))['status'] in ('blocked', 'failed')
    assert list(group.iterdir()) == [group / 'collection.md']


def test_move_group_regroup_and_ungroup_preserves_originals_and_topic_paths(tmp_path, monkeypatch):
    def download(url, output):
        output.write_bytes(b'original fixture bytes')
        return 'image/jpeg', url
    monkeypatch.setattr(archive_cli, '_download', download)
    value = request(tmp_path, files=[asset()])
    assert collect(tmp_path, value)['status'] == 'complete'
    base = tmp_path / 'vault/archives'
    current = base / SLUG
    original_digest = digest(current / 'originals' / value['files'][0]['name'])
    topic = tmp_path / 'vault/topics/repair'
    (topic / 'cards').mkdir(parents=True)
    (topic / '02-outline.md').write_text('---\ntype: topic\nkind: outline\ntitle: Repair research\n'
        'subquestions:\n  - id: scope\n    question: What does the manual cover?\n'
        '    coverage: covered\n    cards:\n      - manual\n---\n')
    card = topic / 'cards/manual.md'
    def write_card(directory):
        path = (directory / 'archive.md').relative_to(tmp_path).as_posix()
        TopicSchema.model_validate({'type': 'topic', 'kind': 'card', 'title': 'Repair evidence', 'archives': [path]})
        card.write_text(f'---\ntype: topic\nkind: card\ntitle: Repair evidence\narchives:\n  - {path}\n---\n')
    def card_usable():
        return topic_status(tmp_path, 'repair')['facts']['outline']['projection']['cards'][0]['artifact']['usable']
    write_card(current)
    assert card_usable()
    for name in ('集', '维修 材料', None):
        observed = archive_status(tmp_path, SLUG)
        stale = {**value, 'expected_revision': observed['facts']['collection']['revision'], 'files': []}
        destination = base if name is None else base / name
        if name:
            destination.mkdir()
            (destination / 'collection.md').write_text('')
        current.rename(destination / SLUG)
        current = destination / SLUG
        assert not card_usable()  # Finder-style moves need external references repaired.
        assert collect(tmp_path, stale)['status'] == 'blocked'
        observed = archive_status(tmp_path, SLUG)
        canonical = (current / 'archive.md').relative_to(tmp_path).as_posix()
        assert observed['facts']['canonical']['path'] == canonical
        assert observed['facts']['collection']['usable']
        assert {'kind': 'archive', 'slug': SLUG} in scan_status(tmp_path)['items']
        for query in ({'kind': 'archive', 'slug': SLUG}, {'kind': 'archive', 'slug': 'new-name', 'url': URL}):
            assert resolve(tmp_path, [query])['resolved'][0]['path'] == canonical
        fresh = {**stale, 'expected_revision': observed['facts']['collection']['revision'], 'topics': ['second-topic']}
        assert collect(tmp_path, fresh)['path'] == canonical
        assert digest(current / 'originals' / value['files'][0]['name']) == original_digest
        assert len(archive_pages(tmp_path)) == 1
        write_card(current)
        assert card_usable()
        status = archive_status(tmp_path, SLUG)
        result = run_generated_workflow('archive', {
            'seed': {'state': 'canonical', 'material_slug': SLUG, 'identity': value['identity']},
            'observation': status, 'options': {'topics': ['repair']}}, [audit_complete()], capture_agent_requests=True)
        assert result['value']['terminal'] == 'complete', result
        assert result['value']['artifacts'] == [
            {'role': 'canonical', 'path': canonical},
            {'role': 'manifest', 'path': status['facts']['collection']['path']},
            {'role': 'source', 'path': status['facts']['collection']['files'][0]['path']}]
        from test_workflow_dispatch import _prompt_request
        envelope = _prompt_request(result['agentRequests'][0]['prompt'])
        assert envelope['target'] == {'role': 'canonical', 'path': canonical}


def _hold_collector_lock(root, ready, release):
    with archive_cli._lock(Path(root), {'slug': SLUG, 'url': URL}):
        ready.set()
        release.wait(10)


def test_active_collector_blocks_marple_move_in_another_process(tmp_path):
    context = multiprocessing.get_context('spawn')
    ready, release = context.Event(), context.Event()
    process = context.Process(target=_hold_collector_lock, args=(str(tmp_path), ready, release))
    process.start()
    try:
        assert ready.wait(10)
        with (tmp_path / '.marple/archive-collections.lock').open('r+') as stream:
            with pytest.raises(BlockingIOError):
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        release.set()
        process.join(10)
        if process.is_alive():
            process.kill()
            process.join()
    assert process.exitcode == 0
    with (tmp_path / '.marple/archive-collections.lock').open('r+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
