import os
import sqlite3
import pytest

from gotham.core import sbx


def _docker_ok():
    return sbx.docker_available()


needs_docker = pytest.mark.skipif(not _docker_ok(), reason='Docker daemon required for real-execution acceptance tests')


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('GOTHAM_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('GOTHAM_AUDIT_DB', str(tmp_path / 'audit' / 'specter.sqlite3'))
    monkeypatch.setenv('GOTHAM_STORE_DB', str(tmp_path / 'data' / 'gotham.sqlite3'))
    return tmp_path


@pytest.fixture()
def alfred(env):
    from gotham.core.engine import Alfred
    return Alfred()


def run_until_done(alfred, concurrency=4, **kw):
    from gotham.core.worker import run_worker
    run_worker(alfred, once=True, concurrency=concurrency, poll=0.1, **kw)


def pytest_collection_modifyitems(config, items):
    """Tier the suite: anything that needs the Docker daemon is `integration`; anything that needs the research image is `research`."""
    for item in items:
        for m in item.iter_markers('skipif'):
            if 'Docker daemon required' in str(m.kwargs.get('reason', '')):
                item.add_marker(pytest.mark.integration)
        if item.get_closest_marker('integration') and ('notebook' in item.name or 'all_five' in item.name):
            item.add_marker(pytest.mark.research)
