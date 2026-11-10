"""Runtime configuration for Gotham 4.0. Secrets are read from the environment only."""
from __future__ import annotations
import os
from pathlib import Path


def data_dir() -> Path:
    p = Path(os.environ.get('GOTHAM_DATA_DIR', Path.cwd() / 'data')).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def workspaces_dir() -> Path:
    p = data_dir() / 'workspaces'
    p.mkdir(parents=True, exist_ok=True)
    return p


def artifacts_dir() -> Path:
    p = data_dir() / 'artifacts'
    p.mkdir(parents=True, exist_ok=True)
    return p


def store_path() -> Path:
    return Path(os.environ.get('GOTHAM_STORE_DB', data_dir() / 'gotham.sqlite3'))


def audit_path() -> Path:
    """The audit journal lives OUTSIDE the data dir the workers can reach by default."""
    default = data_dir().parent / (data_dir().name + '-audit') / 'specter.sqlite3'
    return Path(os.environ.get('GOTHAM_AUDIT_DB', default))


SANDBOX_IMAGE = os.environ.get('GOTHAM_SANDBOX_IMAGE', 'python:3.12-alpine')
RESEARCH_IMAGE = os.environ.get('GOTHAM_RESEARCH_IMAGE', 'gotham-research:latest')
LEASE_SECONDS = int(os.environ.get('GOTHAM_LEASE_SECONDS', '30'))
MAX_ATTEMPTS = int(os.environ.get('GOTHAM_MAX_ATTEMPTS', '2'))
