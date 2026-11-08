"""No host-side execution of user code; all executions require disposable Docker containers."""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

IMAGE = os.environ.get('GOTHAM_SANDBOX_IMAGE', 'python:3.12-alpine')
MAX_OUTPUT = 8000

# This code is copied to a throwaway, read-only container and runs there, never in FastAPI.
RUNNER = r'''import json,runpy,sys,traceback
try:
    values=runpy.run_path('/work/solution.py',run_name='gotham_solution')
    values['__name__']='__gotham_tests__'
    exec(compile(open('/work/tests.py',encoding='utf-8').read(),'/work/tests.py','exec'), values)
    print('GOTHAM_TESTS_PASSED')
except BaseException:
    traceback.print_exc()
    sys.exit(1)
'''

class SandboxUnavailable(RuntimeError): pass


def run_isolated(code: str, tests: str, *, timeout: int = 5) -> dict:
    """Execute untrusted code in disposable locked-down Docker, never with local exec()."""
    if len(code.encode('utf-8')) > 12000 or len(tests.encode('utf-8')) > 6000:
        raise ValueError('Source exceeds sandbox size limits')
    run_id = 'gotham-' + uuid.uuid4().hex[:20]
    with tempfile.TemporaryDirectory(prefix='gotham-task-', dir=os.environ.get('GOTHAM_SANDBOX_TMPDIR') or None) as folder:
        root = Path(folder)
        (root / 'solution.py').write_text(code, encoding='utf-8')
        (root / 'tests.py').write_text(tests, encoding='utf-8')
        (root / 'runner.py').write_text(RUNNER, encoding='utf-8')
        root.chmod(0o755)
        for item in root.iterdir(): item.chmod(0o644)
        cmd = [
            'docker', 'run', '--rm', '--name', run_id, '--pull=never',
            '--network=none', '--read-only', '--cap-drop=ALL',
            '--security-opt=no-new-privileges', '--pids-limit=32',
            '--memory=128m', '--memory-swap=128m', '--cpus=0.5',
            '--user=65534:65534', '--tmpfs=/tmp:rw,noexec,nosuid,size=8m',
            '--mount', f'type=bind,src={root},dst=/work,readonly',
            '--workdir=/work', IMAGE, 'python', '-B', '-I', '/work/runner.py'
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            # If Docker CLI is killed by subprocess timeout, remove the container explicitly.
            try:
                removed = subprocess.run(['docker','rm','-f',run_id],capture_output=True,text=True,timeout=5,check=False)
            except (OSError,subprocess.TimeoutExpired) as exc:
                raise SandboxUnavailable('Sandbox timed out; container cleanup could not be verified') from exc
            if removed.returncode != 0 and 'No such container' not in removed.stderr:
                raise SandboxUnavailable('Sandbox timed out; container cleanup was unsuccessful')
            return {'passed':False, 'timed_out':True, 'exit_code':124, 'output':'Sandbox stopped at execution time limit',
                    'sandbox':'docker', 'network':'none', 'container_destroyed':True,
                    'code_sha256':hashlib.sha256(code.encode()).hexdigest()}
        except OSError as exc:
            raise SandboxUnavailable('Docker CLI is not available; no user code executed') from exc
        output=(result.stdout+'\n'+result.stderr).strip()[:MAX_OUTPUT]
        if result.returncode == 125:
            raise SandboxUnavailable('Docker could not start the isolated container: '+output[:300])
        # --rm requests cleanup, but do not report it as proven without inspecting.
        # An inspect error other than an explicit "No such object" is NOT proof of removal.
        destroyed=False
        try:
            inspection=subprocess.run(['docker','container','inspect',run_id],capture_output=True,
                                      text=True,timeout=5,check=False)
            missing=(inspection.returncode != 0 and
                     ('No such object' in inspection.stderr or 'No such container' in inspection.stderr))
            destroyed=bool(missing)
            if not destroyed and inspection.returncode == 0:
                subprocess.run(['docker','rm','-f',run_id],capture_output=True,text=True,timeout=5,check=False)
        except (OSError,subprocess.TimeoutExpired):
            destroyed=False
        return {
            'passed':result.returncode==0 and 'GOTHAM_TESTS_PASSED' in result.stdout,
            'timed_out':False, 'exit_code':result.returncode, 'output':output,
            'sandbox':'docker', 'network':'none','container_destroyed':destroyed,
            'code_sha256':hashlib.sha256(code.encode()).hexdigest(),
        }


def containment_probe() -> dict:
    """CPU infinite loop should stop at timeout and be forcibly removed."""
    result = run_isolated('while True:\n    pass\n', 'assert True', timeout=2)
    return {'probe':'cpu_infinite_loop', 'contained':result['timed_out'] and result['container_destroyed'], 'evidence':result}
