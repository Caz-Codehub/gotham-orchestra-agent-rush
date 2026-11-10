"""Oracle research tools: real Jupyter execution, resumable training, dataset validation, statistics.
Everything executes inside the network-less research container; the host never runs notebook code."""
from __future__ import annotations
import json
import re
import shutil
import subprocess
from pathlib import Path

import nbformat

from . import config, sbx
from .tools import ToolError, tool

ASSETS = Path(__file__).parent / 'assets'
EXEC_SCRIPT = r'''
import sys, json, nbformat
from nbclient import NotebookClient
src, dst, timeout = sys.argv[1], sys.argv[2], int(sys.argv[3])
nb = nbformat.read(src, as_version=4)
c = NotebookClient(nb, timeout=timeout, kernel_name='python3', allow_errors=False, resources={'metadata': {'path': '/work'}})
status, err = 'ok', None
try:
    c.execute()
except Exception as e:
    status, err = 'error', f'{type(e).__name__}: {str(e)[-1500:]}'
nbformat.write(nb, dst)
cells = [x for x in nb.cells if x.cell_type == 'code']
print('GOTHAM_NB ' + json.dumps({'status': status, 'error': err, 'code_cells': len(cells),
      'executed_cells': sum(1 for x in cells if x.get('execution_count'))}))
sys.exit(0 if status == 'ok' else 1)
'''


def _gpu():
    try:
        r = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader'], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


@tool('compute_info', 'Report available compute for experiments (CPU count, GPU presence, docker research image).', {}, ('Oracle', 'Scout'))
def compute_info(ctx):
    import os
    return {'cpus': os.cpu_count(), 'gpu': _gpu() or 'none detected', 'research_image': config.RESEARCH_IMAGE,
            'research_image_present': sbx.image_present(config.RESEARCH_IMAGE), 'backends': ['local-docker-cpu']}


@tool('notebook_create', 'Create a Jupyter notebook in the workspace from a list of cells.',
      {'name': ('str', True, 'notebook file name without extension'), 'cells': ('list', True, 'list of {"type":"code|markdown","source":"..."}')},
      ('Oracle',))
def notebook_create(ctx, name, cells):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,60}', name):
        raise ToolError('invalid notebook name')
    nb = nbformat.v4.new_notebook()
    nb.metadata['kernelspec'] = {'name': 'python3', 'display_name': 'Python 3', 'language': 'python'}
    for c in cells:
        if not isinstance(c, dict) or c.get('type') not in ('code', 'markdown') or not isinstance(c.get('source'), str):
            raise ToolError('each cell needs type code|markdown and string source')
        nb.cells.append(nbformat.v4.new_code_cell(c['source']) if c['type'] == 'code' else nbformat.v4.new_markdown_cell(c['source']))
    nbformat.validate(nb)
    path = ctx.path(f'{name}.ipynb')
    nbformat.write(nb, path)
    return {'notebook': path.name, 'cells': len(nb.cells), 'valid': True}


@tool('notebook_execute', 'Execute a notebook top-to-bottom in the sandboxed research kernel. Fails if any cell errors.',
      {'name': ('str', True, 'notebook name without extension'), 'timeout': ('int', False, 'seconds, max 600')}, ('Oracle',), risk='medium')
def notebook_execute(ctx, name, timeout=300):
    src = ctx.path(f'{name}.ipynb')
    if not src.is_file():
        raise ToolError('notebook not found')
    sbx.ensure_image(config.RESEARCH_IMAGE)
    shutil.copyfile(ASSETS / 'trainer.py', ctx.workspace / '_trainer.py') if (ASSETS / 'trainer.py').exists() else None
    (ctx.workspace / '_nbexec.py').write_text(EXEC_SCRIPT)
    t = ctx.remaining(min(timeout, 600))
    r = sbx.run(config.RESEARCH_IMAGE, ['python', '/work/_nbexec.py', f'/work/{name}.ipynb', f'/work/{name}.executed.ipynb', str(max(10, t - 5))],
                mount=ctx.workspace, rw=True, timeout=t, memory='1g', cpus='2', pids=256, tmpfs='128m',
                env={'JUPYTER_RUNTIME_DIR': '/tmp/jr', 'JUPYTER_DATA_DIR': '/tmp/jd', 'IPYTHONDIR': '/tmp/ip', 'MPLCONFIGDIR': '/tmp/mpl'})
    m = re.search(r'GOTHAM_NB (\{.*\})', r['stdout'])
    info = json.loads(m.group(1)) if m else {'status': 'error', 'error': (r['stderr'] or r['stdout'])[-600:]}
    outputs = []
    ex = ctx.workspace / f'{name}.executed.ipynb'
    if ex.exists():
        for c in nbformat.read(ex, as_version=4).cells:
            if c.cell_type == 'code':
                for o in c.get('outputs', []):
                    txt = o.get('text') or (o.get('data', {}).get('text/plain') if 'data' in o else None) or o.get('evalue')
                    if txt:
                        outputs.append(str(txt)[:300])
    ok = info['status'] == 'ok' and r['exit_code'] == 0 and ex.exists() and info.get('executed_cells', 0) == info.get('code_cells', -1)
    return {'ok': ok, 'executed_notebook': ex.name if ex.exists() else None, **info, 'outputs': outputs[:20],
            'container_destroyed': r['container_destroyed'], 'network': r['network'], 'elapsed_ms': r['elapsed_ms']}


@tool('train_model', 'Run the resumable training job (SGD classifier) with checkpoints and metric tracking in the research sandbox.',
      {'epochs': ('int', False, 'default 10'), 'lr': ('str', False, 'learning rate, default 0.01'), 'seed': ('int', False, 'default 0'),
       'resume': ('bool', False, 'resume from checkpoint'), 'stop_after': ('int', False, 'simulate interruption after N epochs'),
       'csv': ('str', False, 'workspace csv with label column')}, ('Oracle',), risk='medium')
def train_model(ctx, epochs=10, lr='0.01', seed=0, resume=False, stop_after=0, csv=''):
    if not 1 <= epochs <= 200:
        raise ToolError('epochs must be 1..200')
    float(lr)
    sbx.ensure_image(config.RESEARCH_IMAGE)
    shutil.copyfile(ASSETS / 'trainer.py', ctx.workspace / '_trainer.py')
    cmd = ['python', '/work/_trainer.py', '--epochs', str(epochs), '--lr', str(float(lr)), '--seed', str(seed)]
    if resume:
        cmd.append('--resume')
    if stop_after:
        cmd += ['--stop-after', str(stop_after)]
    if csv:
        ctx.path(csv)
        cmd += ['--csv', f'/work/{csv}']
    r = sbx.run(config.RESEARCH_IMAGE, cmd, mount=ctx.workspace, rw=True, timeout=ctx.remaining(300), memory='1g', cpus='2', tmpfs='128m')
    metrics = []
    mp = ctx.workspace / 'metrics.jsonl'
    if mp.exists():
        metrics = [json.loads(l) for l in mp.read_text().splitlines() if l.strip()]
    return {'ok': r['exit_code'] == 0, 'interrupted': r['exit_code'] == 75, 'exit_code': r['exit_code'],
            'resumed': 'RESUMED' in r['stdout'], 'epochs_logged': len(metrics), 'last_metrics': metrics[-1] if metrics else None,
            'checkpoint_exists': (ctx.workspace / 'ckpt' / 'last.pkl').exists(), 'stderr': r['stderr'][-400:],
            'container_destroyed': r['container_destroyed']}


@tool('dataset_validate', 'Load a CSV and report shape, dtypes, nulls, duplicates and a content hash.',
      {'path': ('str', True, 'csv path')}, ('Oracle',))
def dataset_validate(ctx, path):
    import hashlib
    import pandas as pd
    p = ctx.path(path)
    if not p.is_file() or p.stat().st_size > 50_000_000:
        raise ToolError('dataset missing or too large')
    df = pd.read_csv(p)
    return {'rows': len(df), 'columns': list(df.columns), 'dtypes': {k: str(v) for k, v in df.dtypes.items()},
            'null_counts': {k: int(v) for k, v in df.isna().sum().items()}, 'duplicate_rows': int(df.duplicated().sum()),
            'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'valid': bool(len(df) and not df.isna().all().any())}
