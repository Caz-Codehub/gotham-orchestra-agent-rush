"""Tool registry: the ONLY way agents touch the world.

Every call is (1) checked against the calling agent's allowlist, (2) argument-validated,
(3) gated by approval when the tool is high-risk, (4) executed with a deadline, and (5) written to the
independent audit journal (start + result digest). Agents never receive credentials, the audit handle,
or paths outside their task workspace.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import config, sbx


class ToolDenied(Exception):
    """Permission/scope policy refused the call."""


class ApprovalRequired(Exception):
    def __init__(self, tool, detail):
        super().__init__(f'approval required for {tool}')
        self.tool, self.detail = tool, detail


class ToolError(Exception):
    pass


class TaskCancelled(Exception):
    pass


@dataclass
class ToolContext:
    mission_id: str
    task_id: str
    agent: str
    workspace: Path
    store: Any
    audit: Any            # AuditWriter (record-only)
    deadline: float = 0.0  # monotonic
    scope: dict = field(default_factory=dict)  # authorized targets for active testing
    is_cancelled: Callable = lambda: False
    max_calls: int = 300
    calls: int = 0

    def remaining(self, cap: int) -> int:
        if not self.deadline:
            return cap
        left = int(self.deadline - time.monotonic())
        if left <= 1:
            raise ToolError('task deadline exceeded')
        return min(cap, left)

    def path(self, rel: str) -> Path:
        """Resolve a workspace-relative path; reject escapes, absolute paths and symlink tricks."""
        if not isinstance(rel, str) or '\x00' in rel:
            raise ToolDenied('invalid path')
        p = (self.workspace / rel).resolve()
        root = self.workspace.resolve()
        if p != root and root not in p.parents:
            raise ToolDenied(f'path escapes workspace: {rel[:80]}')
        return p

    def record(self, action, detail=None):
        self.audit.record(self.mission_id, self.task_id, self.agent, action, detail or {})


@dataclass
class Tool:
    name: str
    description: str
    params: dict          # name -> (type, required, description)
    fn: Callable
    risk: str = 'low'     # low | medium | high
    agents: tuple = ()    # allowed agents; empty = none


REGISTRY: dict[str, Tool] = {}
TYPES = {'str': str, 'int': int, 'bool': bool, 'list': list, 'dict': dict}


def tool(name, description, params, agents, risk='low'):
    def deco(fn):
        REGISTRY[name] = Tool(name, description, params, fn, risk, tuple(agents))
        return fn
    return deco


def specs_for(agent: str) -> list[dict]:
    return [{'name': t.name, 'description': t.description, 'risk': t.risk,
             'params': {k: {'type': v[0], 'required': v[1], 'description': v[2]} for k, v in t.params.items()}}
            for t in REGISTRY.values() if agent in t.agents]


def _validate(t: Tool, args: dict) -> dict:
    if not isinstance(args, dict):
        raise ToolError('arguments must be an object')
    unknown = set(args) - set(t.params)
    if unknown:
        raise ToolError(f'unknown arguments: {sorted(unknown)}')
    out = {}
    for k, (typ, req, _d) in t.params.items():
        if k not in args:
            if req:
                raise ToolError(f'missing required argument: {k}')
            continue
        v = args[k]
        if typ == 'int' and isinstance(v, bool):
            raise ToolError(f'{k} must be int')
        if not isinstance(v, TYPES[typ]):
            raise ToolError(f'{k} must be {typ}')
        if typ == 'str' and len(v) > 400_000:
            raise ToolError(f'{k} too large')
        out[k] = v
    return out


def call(ctx: ToolContext, name: str, args: dict) -> Any:
    t = REGISTRY.get(name)
    if t is None:
        ctx.record('policy_violation_unknown_tool', {'tool': name})
        raise ToolDenied(f'unknown tool: {name}')
    if ctx.agent not in t.agents:
        ctx.record('policy_violation_tool_not_permitted', {'tool': name, 'agent': ctx.agent})
        raise ToolDenied(f'{ctx.agent} is not permitted to use {name}')
    if ctx.is_cancelled():
        raise TaskCancelled('mission cancelled')
    ctx.calls += 1
    if ctx.calls > ctx.max_calls:
        ctx.record('policy_violation_quota', {'tool': name, 'max_calls': ctx.max_calls})
        raise ToolDenied('tool-call quota exhausted for this task')
    clean = _validate(t, args)
    if t.risk == 'high' and not ctx.store.has_approval(ctx.task_id, f'tool:{name}'):
        ctx.record('approval_required', {'tool': name})
        raise ApprovalRequired(name, {'tool': name, 'args': {k: str(v)[:200] for k, v in clean.items()}})
    arg_digest = hashlib.sha256(json.dumps(clean, sort_keys=True, default=str).encode()).hexdigest()
    ctx.record('tool_call', {'tool': name, 'risk': t.risk, 'args_sha256': arg_digest,
                             'args_preview': {k: (v[:120] if isinstance(v, str) else v) for k, v in clean.items()}})
    t0 = time.monotonic()
    try:
        result = t.fn(ctx, **clean)
    except (ToolDenied, ApprovalRequired, TaskCancelled):
        raise
    except Exception as exc:
        ctx.record('tool_result', {'tool': name, 'ok': False, 'error': str(exc)[:300],
                                   'elapsed_ms': round((time.monotonic() - t0) * 1000)})
        raise
    blob = json.dumps(result, sort_keys=True, default=str)
    ctx.store.add_usage(ctx.mission_id, ctx.task_id, 'tool_calls', 1)
    if isinstance(result, dict) and isinstance(result.get('elapsed_ms'), int):
        ctx.store.add_usage(ctx.mission_id, ctx.task_id, 'sandbox_ms', result['elapsed_ms'])
    ctx.record('tool_result', {'tool': name, 'ok': True, 'result_sha256': hashlib.sha256(blob.encode()).hexdigest(),
                               'elapsed_ms': round((time.monotonic() - t0) * 1000)})
    return result


ALL = ('Scout', 'Forge', 'Oracle', 'Sentinel', 'Cipher')

# ------------------------------------------------------------------ filesystem
@tool('fs_list', 'List files in a workspace directory.', {'path': ('str', False, 'relative dir, default .')}, ALL)
def fs_list(ctx, path='.'):
    base = ctx.path(path)
    if not base.is_dir():
        raise ToolError('not a directory')
    items = []
    for p in sorted(base.rglob('*')):
        if '.git' in p.parts or '.deps' in p.parts or p.is_symlink():
            continue
        items.append({'path': str(p.relative_to(ctx.workspace)), 'type': 'dir' if p.is_dir() else 'file',
                      'size': p.stat().st_size if p.is_file() else 0})
        if len(items) >= 500:
            break
    return {'items': items}


@tool('fs_read', 'Read a text file from the workspace (max 100KB returned).', {'path': ('str', True, 'relative file')}, ALL)
def fs_read(ctx, path):
    p = ctx.path(path)
    if not p.is_file():
        raise ToolError('not a file')
    data = p.read_bytes()
    return {'path': path, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'content': data[:100_000].decode('utf-8', 'replace'), 'truncated': len(data) > 100_000}


@tool('fs_write', 'Write a text file in the workspace.', {'path': ('str', True, 'relative file'), 'content': ('str', True, 'file content')},
      ALL)
def fs_write(ctx, path, content):
    p = ctx.path(path)
    if '.git' in p.relative_to(ctx.workspace.resolve()).parts:
        raise ToolDenied('direct writes to .git are not allowed')
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding='utf-8')
    return {'path': path, 'bytes': len(content.encode()), 'sha256': hashlib.sha256(content.encode()).hexdigest()}


@tool('emit_artifact', 'Publish a workspace file as a tracked, hashed mission artifact.',
      {'path': ('str', True, 'relative file'), 'name': ('str', False, 'artifact name')}, ALL)
def emit_artifact(ctx, path, name=''):
    p = ctx.path(path)
    if not p.is_file():
        raise ToolError('not a file')
    dest_dir = config.artifacts_dir() / ctx.mission_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    nm = re.sub(r'[^A-Za-z0-9._-]', '_', name or p.name)[:100]
    dest = dest_dir / f'{ctx.task_id[:8]}-{nm}'
    shutil.copyfile(p, dest)
    data = dest.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    aid = ctx.store.add_artifact(ctx.mission_id, ctx.task_id, nm, dest, sha, len(data), ctx.agent)
    ctx.record('artifact_created', {'artifact_id': aid, 'name': nm, 'sha256': sha, 'size': len(data)})
    return {'artifact_id': aid, 'name': nm, 'sha256': sha, 'size': len(data)}

# ------------------------------------------------------------------ execution
@tool('sandbox_run', 'Run a command in a disposable network-less container with the workspace mounted read-write.',
      {'cmd': ('list', True, 'argv list, e.g. ["python","main.py"]'), 'timeout': ('int', False, 'seconds, max 300')},
      ('Forge', 'Oracle', 'Cipher'), risk='medium')
def sandbox_run(ctx, cmd, timeout=60):
    if not cmd or not all(isinstance(c, str) for c in cmd):
        raise ToolError('cmd must be a non-empty list of strings')
    sbx.ensure_image('gotham-sandbox:latest')
    env = {'PYTHONPATH': '/work:/work/.deps'}
    return sbx.run('gotham-sandbox:latest', cmd, mount=ctx.workspace, rw=True, timeout=ctx.remaining(min(timeout, 300)), env=env)


@tool('run_tests', 'Run the project test-suite (pytest) in the sandbox and return a structured result.',
      {'args': ('list', False, 'extra pytest args'), 'timeout': ('int', False, 'seconds')}, ('Forge', 'Oracle'), risk='medium')
def run_tests(ctx, args=None, timeout=120):
    sbx.ensure_image('gotham-sandbox:latest')
    extra = [a for a in (args or []) if isinstance(a, str) and not a.startswith(('--rootdir', '-c', '-p', '--import-mode'))]
    cmd = ['python', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '--tb=short', *extra]
    r = sbx.run('gotham-sandbox:latest', cmd, mount=ctx.workspace, rw=True, timeout=ctx.remaining(min(timeout, 300)),
                env={'PYTHONPATH': '/work:/work/.deps'})
    out = r['stdout'] + r['stderr']
    m = re.search(r'(\d+) passed', out)
    f = re.search(r'(\d+) failed', out)
    e = re.search(r'(\d+) error', out)
    r['summary'] = {'passed': int(m.group(1)) if m else 0, 'failed': int(f.group(1)) if f else 0,
                    'errors': int(e.group(1)) if e else 0}
    r['ok'] = r['exit_code'] == 0 and r['summary']['passed'] > 0 and not r['timed_out']
    return r


@tool('install_deps', 'Install Python requirements into workspace/.deps (network enabled, pip only, no secrets mounted).',
      {'requirements': ('str', False, 'requirements file, default requirements.txt')}, ('Forge',), risk='medium')
def install_deps(ctx, requirements='requirements.txt'):
    ctx.path(requirements)
    if not re.fullmatch(r'[A-Za-z0-9._/-]+', requirements):
        raise ToolDenied('bad requirements path')
    sbx.ensure_image('gotham-sandbox:latest')
    env = {'PIP_DISABLE_PIP_VERSION_CHECK': '1'}
    ca = os.environ.get('GOTHAM_BUILD_CA_BUNDLE')
    ro = [(Path(ca), '/tmp/ca.crt')] if ca and Path(ca).is_file() else []
    if ro:
        env['PIP_CERT'] = '/tmp/ca.crt'
    r = sbx.run('gotham-sandbox:latest', ['pip', 'install', '--no-cache-dir', '--target', '/work/.deps', '-r', requirements],
                mount=ctx.workspace, rw=True, network=True, timeout=ctx.remaining(240), env=env, ro_mounts=ro, memory='512m')
    r['ok'] = r['exit_code'] == 0
    return r

# ------------------------------------------------------------------ git (host git, hooks disabled)
def _git(ctx, *args, check=True):
    env = {'PATH': os.environ.get('PATH', ''), 'HOME': str(ctx.workspace), 'GIT_CONFIG_NOSYSTEM': '1',
           'GIT_AUTHOR_NAME': f'Gotham {ctx.agent}', 'GIT_AUTHOR_EMAIL': f'{ctx.agent.lower()}@gotham.local',
           'GIT_COMMITTER_NAME': f'Gotham {ctx.agent}', 'GIT_COMMITTER_EMAIL': f'{ctx.agent.lower()}@gotham.local',
           'GIT_TERMINAL_PROMPT': '0'}
    r = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', '-c', 'protocol.ext.allow=never',
                        *args], cwd=ctx.workspace, capture_output=True, text=True, timeout=60, env=env)
    if check and r.returncode != 0:
        raise ToolError(f'git {args[0]} failed: {r.stderr[-300:]}')
    return r


@tool('git_init', 'Initialise a git repository in the workspace (idempotent).', {}, ('Forge',))
def git_init(ctx):
    _git(ctx, 'init', '-q', '-b', 'main')
    gi = ctx.workspace / '.gitignore'
    if not gi.exists():
        gi.write_text('.deps/\n__pycache__/\n*.pyc\n.pytest_cache/\n')
    return {'ok': True}


@tool('git_branch', 'Create and switch to a branch.', {'name': ('str', True, 'branch name')}, ('Forge',))
def git_branch(ctx, name):
    if not re.fullmatch(r'[A-Za-z0-9._/-]{1,80}', name) or name.startswith('-'):
        raise ToolDenied('bad branch name')
    _git(ctx, 'checkout', '-q', '-B', name)
    return {'branch': name}


@tool('git_status', 'Show git status (porcelain).', {}, ('Forge', 'Scout'))
def git_status(ctx):
    return {'status': _git(ctx, 'status', '--porcelain').stdout}


@tool('git_diff', 'Show the working-tree diff against HEAD.', {}, ('Forge', 'Scout'))
def git_diff(ctx):
    return {'diff': _git(ctx, 'diff', 'HEAD', check=False).stdout[-50000:]}


@tool('git_log', 'Show recent commits.', {}, ('Forge', 'Scout'))
def git_log(ctx):
    r = _git(ctx, 'log', '--oneline', '-n', '20', check=False)
    return {'log': r.stdout}


@tool('git_commit', 'Stage everything and commit.', {'message': ('str', True, 'commit message')}, ('Forge',))
def git_commit(ctx, message):
    _git(ctx, 'add', '-A')
    r = _git(ctx, 'commit', '-q', '-m', message[:500], check=False)
    if r.returncode != 0 and 'nothing to commit' not in (r.stdout + r.stderr):
        raise ToolError('commit failed: ' + r.stderr[-300:])
    sha = _git(ctx, 'rev-parse', 'HEAD').stdout.strip()
    return {'commit': sha, 'message': message[:500]}
