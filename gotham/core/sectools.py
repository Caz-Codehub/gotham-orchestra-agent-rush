"""Defensive-security and malware-analysis tools. Static analysis runs on the host against files only;
anything that EXECUTES a sample runs in the network-less sandbox."""
from __future__ import annotations
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from . import sbx
from .tools import ToolContext, ToolDenied, ToolError, tool

ROOT = Path(__file__).resolve().parents[2]
SEMGREP_RULES = ROOT / 'rules' / 'semgrep'
SEC_AGENTS = ('Sentinel', 'Cipher')
SECRET_RES = {
    'aws_access_key': re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    'private_key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'github_token': re.compile(r'\bgh[pousr]_[A-Za-z0-9]{30,}\b'),
    'generic_secret_assignment': re.compile(r'(?i)\b(?:password|passwd|secret|api[_-]?key|token)\b\s*[:=]\s*["\'][^"\']{8,}["\']'),
}
SKIP_DIRS = {'.git', '.deps', 'node_modules', '__pycache__', '.venv'}


def _walk(base: Path):
    for p in base.rglob('*'):
        if p.is_file() and not p.is_symlink() and not (SKIP_DIRS & set(p.parts)):
            yield p


def _finding(rule, severity, path, line, message, evidence='', **extra):
    return {'rule': rule, 'severity': severity, 'file': path, 'line': line, 'message': message,
            'evidence': evidence[:200], **extra}

# ------------------------------------------------------------------ Sentinel: static analysis
@tool('semgrep_scan', 'Static code security analysis with Semgrep using the bundled Gotham rule-pack.',
      {'path': ('str', False, 'relative dir or file, default .')}, ('Sentinel', 'Scout'))
def semgrep_scan(ctx, path='.'):
    target = ctx.path(path)
    exe = shutil.which('semgrep') or str(Path(sys.executable).parent / 'semgrep')
    if not Path(exe).exists():
        raise ToolError('semgrep is not installed')
    r = subprocess.run([exe, 'scan', '--config', str(SEMGREP_RULES), '--json', '--metrics=off', '--disable-version-check',
                        '--quiet', '--timeout', '20', str(target)], capture_output=True, text=True,
                       timeout=ctx.remaining(180), env={**os.environ, 'SEMGREP_SEND_METRICS': 'off'})
    if r.returncode not in (0, 1):
        raise ToolError('semgrep failed: ' + r.stderr[-300:])
    data = json.loads(r.stdout or '{}')
    findings = []
    for x in data.get('results', []):
        rel = os.path.relpath(x['path'], ctx.workspace)
        findings.append(_finding(x['check_id'][x['check_id'].find('gotham.'):] if 'gotham.' in x['check_id'] else x['check_id'], {'ERROR': 'high', 'WARNING': 'medium'}.get(x['extra']['severity'], 'low'),
                                 rel, x['start']['line'], x['extra']['message'], x['extra'].get('lines', ''),
                                 cwe=(x['extra'].get('metadata') or {}).get('cwe')))
    return {'engine': 'semgrep', 'version': data.get('version'), 'rules': str(SEMGREP_RULES.relative_to(ROOT)),
            'findings': findings, 'errors': len(data.get('errors', []))}


@tool('secrets_scan', 'Scan workspace files for committed credentials.', {'path': ('str', False, 'dir, default .')}, ('Sentinel',))
def secrets_scan(ctx, path='.'):
    base = ctx.path(path)
    findings = []
    for p in _walk(base):
        if p.stat().st_size > 1_000_000:
            continue
        try:
            text = p.read_text('utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for name, rx in SECRET_RES.items():
                if rx.search(line):
                    findings.append(_finding('secret.' + name, 'high', str(p.relative_to(ctx.workspace)), i,
                                             f'Possible committed credential ({name})', '[redacted]'))
    return {'engine': 'gotham-secrets', 'findings': findings}


@tool('dep_audit', 'Audit pinned Python dependencies against the OSV/PyPI advisory database (pip-audit).',
      {'requirements': ('str', False, 'requirements file, default requirements.txt')}, ('Sentinel',))
def dep_audit(ctx, requirements='requirements.txt'):
    req = ctx.path(requirements)
    if not req.is_file():
        raise ToolError('requirements file not found')
    exe = shutil.which('pip-audit') or str(Path(sys.executable).parent / 'pip-audit')
    if not Path(exe).exists():
        raise ToolError('pip-audit is not installed')
    r = subprocess.run([exe, '-r', str(req), '--no-deps', '--disable-pip', '-f', 'json', '--progress-spinner', 'off'],
                       capture_output=True, text=True, timeout=ctx.remaining(150))
    try:
        data = json.loads(r.stdout)
    except ValueError:
        raise ToolError('pip-audit failed: ' + (r.stderr or r.stdout)[-300:])
    findings = []
    for dep in data.get('dependencies', []):
        for v in dep.get('vulns', []):
            findings.append(_finding('dep.' + v['id'], 'high', requirements, 0,
                                     f"{dep['name']}=={dep['version']} is vulnerable ({v['id']}); fixed in {v.get('fix_versions')}",
                                     dep=dep['name'], version=dep['version'], fix_versions=v.get('fix_versions')))
    return {'engine': 'pip-audit', 'dependencies_checked': len(data.get('dependencies', [])), 'findings': findings}


@tool('config_audit', 'Audit Dockerfile / compose / env files for insecure configuration.',
      {'path': ('str', False, 'dir, default .')}, ('Sentinel',))
def config_audit(ctx, path='.'):
    base = ctx.path(path)
    findings = []
    for p in _walk(base):
        rel = str(p.relative_to(ctx.workspace))
        name = p.name.lower()
        try:
            lines = p.read_text('utf-8').splitlines() if p.stat().st_size < 500_000 else []
        except (UnicodeDecodeError, OSError):
            continue
        if name.startswith('dockerfile') or name.endswith('.dockerfile'):
            has_user = any(l.strip().upper().startswith('USER ') for l in lines)
            if not has_user:
                findings.append(_finding('docker.runs-as-root', 'medium', rel, 1, 'Image has no USER instruction; runs as root'))
            for i, l in enumerate(lines, 1):
                if re.match(r'(?i)\s*FROM\s+\S+:latest\b', l) or re.match(r'(?i)\s*FROM\s+[^:\s@]+\s*$', l):
                    findings.append(_finding('docker.unpinned-base', 'low', rel, i, 'Base image not pinned to a version/digest', l.strip()))
                if re.match(r'(?i)\s*ADD\s+https?://', l):
                    findings.append(_finding('docker.add-remote', 'medium', rel, i, 'ADD from remote URL; verify integrity', l.strip()))
        if name in ('docker-compose.yml', 'docker-compose.yaml', 'compose.yml', 'compose.yaml'):
            for i, l in enumerate(lines, 1):
                if re.search(r'privileged:\s*true', l):
                    findings.append(_finding('compose.privileged', 'high', rel, i, 'Privileged container', l.strip()))
                if 'docker.sock' in l:
                    findings.append(_finding('compose.docker-socket', 'high', rel, i, 'Docker socket mounted into a container', l.strip()))
                if re.search(r'network_mode:\s*["\']?host', l):
                    findings.append(_finding('compose.host-network', 'medium', rel, i, 'Host networking', l.strip()))
        if name.endswith(('.env', '.env.prod')) and name != '.env.example':
            findings.append(_finding('config.env-file-present', 'medium', rel, 1, 'Environment file present in scanned tree'))
    return {'engine': 'gotham-config-audit', 'findings': findings}

# ------------------------------------------------------------------ Sentinel: logs + Sigma
@tool('log_analyze', 'Analyse an auth/web log: brute-force, spraying, scanning and success-after-failure correlation.',
      {'path': ('str', True, 'log file'), 'threshold': ('int', False, 'failures per source to flag, default 5')}, ('Sentinel',))
def log_analyze(ctx, path, threshold=5):
    p = ctx.path(path)
    if not p.is_file():
        raise ToolError('not a file')
    fails, success, users_by_ip, paths_404 = Counter(), defaultdict(list), defaultdict(set), Counter()
    ip_rx = re.compile(r'(\d{1,3}(?:\.\d{1,3}){3})')
    for i, line in enumerate(p.read_text('utf-8', 'replace').splitlines()[:200000], 1):
        m = ip_rx.search(line)
        if not m:
            continue
        ip = m.group(1)
        if re.search(r'(?i)failed password|authentication failure|invalid user|login failed', line):
            fails[ip] += 1
            u = re.search(r'(?i)(?:for|user)(?: invalid user)? (\S+)', line)
            if u:
                users_by_ip[ip].add(u.group(1))
        elif re.search(r'(?i)accepted (?:password|publickey)|login succeeded', line):
            success[ip].append(i)
        elif re.search(r'" 404 ', line):
            paths_404[ip] += 1
    findings = []
    for ip, n in fails.items():
        if n >= threshold:
            findings.append(_finding('log.brute-force', 'high', path, 0, f'{n} failed logins from {ip}', ip=ip, count=n,
                                     technique='T1110'))
            if len(users_by_ip[ip]) >= 3:
                findings.append(_finding('log.password-spraying', 'high', path, 0,
                                         f'{ip} tried {len(users_by_ip[ip])} distinct accounts', ip=ip, technique='T1110.003'))
            if success.get(ip):
                findings.append(_finding('log.success-after-failures', 'critical', path, success[ip][0],
                                         f'Successful login from {ip} after {n} failures: possible compromise', ip=ip,
                                         technique='T1078'))
    for ip, n in paths_404.items():
        if n >= 20:
            findings.append(_finding('log.web-scanning', 'medium', path, 0, f'{n} 404 responses to {ip}: probable scanning', ip=ip))
    return {'engine': 'gotham-log-correlator', 'sources_with_failures': len(fails), 'findings': findings}


def _sigma_match(selection: dict, event: dict) -> bool:
    for key, expected in selection.items():
        field, _, mod = key.partition('|')
        val = event.get(field)
        if val is None:
            return False
        vals = expected if isinstance(expected, list) else [expected]
        s = str(val).lower()

        def ok(e):
            e = str(e).lower()
            return {'contains': e in s, 'startswith': s.startswith(e), 'endswith': s.endswith(e),
                    '': s == e, 're': bool(re.search(str(e), s))}.get(mod, False)
        if not any(ok(e) for e in vals):
            return False
    return True


def _bool_eval(cond: str, env: dict) -> bool:
    """Evaluate `a and (b or not c)` over named selections without eval()."""
    import ast
    tree = ast.parse(cond.strip(), mode='eval')

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.BoolOp):
            vals = [ev(v) for v in n.values]
            return all(vals) if isinstance(n.op, ast.And) else any(vals)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
            return not ev(n.operand)
        if isinstance(n, ast.Name) and n.id in env:
            return env[n.id]
        raise ToolError('unsupported Sigma condition (only and/or/not over named selections)')
    return ev(tree)


def sigma_eval_rule(rule: dict, events: list[dict]) -> list[int]:
    det = rule['detection']
    cond = det['condition']
    names = [k for k in det if k != 'condition']
    hits = []
    for idx, ev in enumerate(events):
        env = {n: _sigma_match(det[n], ev) for n in names}
        if _bool_eval(cond, env):
            hits.append(idx)
    return hits


@tool('sigma_eval', 'Validate a Sigma-compatible rule and run it over JSON-lines events in the workspace.',
      {'rule': ('str', True, 'workspace path of Sigma YAML'), 'events': ('str', True, 'workspace path of JSONL events')},
      ('Sentinel', 'Cipher'))
def sigma_eval(ctx, rule, events):
    r = yaml.safe_load(ctx.path(rule).read_text('utf-8'))
    for key in ('title', 'detection'):
        if key not in r:
            raise ToolError(f'sigma rule missing {key}')
    if 'condition' not in r['detection']:
        raise ToolError('sigma rule missing detection.condition')
    evs = [json.loads(l) for l in ctx.path(events).read_text('utf-8').splitlines() if l.strip()]
    hits = sigma_eval_rule(r, evs)
    return {'rule': r['title'], 'level': r.get('level', 'medium'), 'events': len(evs), 'matches': hits,
            'matched_events': [evs[i] for i in hits[:20]]}

# ------------------------------------------------------------------ Cipher: static triage
def _entropy(b: bytes) -> float:
    if not b:
        return 0.0
    c = Counter(b)
    n = len(b)
    return -sum(v / n * math.log2(v / n) for v in c.values())


def _magic(b: bytes) -> str:
    sig = [(b'\x7fELF', 'ELF executable'), (b'MZ', 'PE/DOS executable'), (b'%PDF', 'PDF'), (b'PK\x03\x04', 'ZIP/Office/JAR'),
           (b'#!', 'script (shebang)'), (b'\xca\xfe\xba\xbe', 'Mach-O fat/Java class'), (b'\x89PNG', 'PNG'), (b'GIF8', 'GIF')]
    for s, n in sig:
        if b.startswith(s):
            return n
    try:
        b[:2000].decode('utf-8')
        return 'text'
    except UnicodeDecodeError:
        return 'binary/unknown'


IOC = {'url': re.compile(rb'https?://[A-Za-z0-9._~:/?#\[\]@!$&\'()*+,;=%-]{4,200}'),
       'ipv4': re.compile(rb'\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b'),
       'domain': re.compile(rb'\b[a-z0-9][a-z0-9-]{1,40}\.(?:com|net|org|io|ru|cn|xyz|top|info|biz)\b', re.I),
       'registry_key': re.compile(rb'HKEY_[A-Z_]+\\[\\A-Za-z0-9_ .-]{3,100}'),
       'email': re.compile(rb'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}\b', re.I)}
SUSPICIOUS_API = [b'CreateRemoteThread', b'VirtualAlloc', b'WriteProcessMemory', b'LoadLibrary', b'WinExec', b'URLDownloadToFile',
                  b'socket', b'connect', b'execve', b'ptrace', b'os.system', b'subprocess', b'base64', b'eval(', b'exec(',
                  b'/etc/passwd', b'/bin/sh']


def _strings(b: bytes, n=6):
    return [m.group().decode('ascii') for m in re.finditer(rb'[\x20-\x7e]{%d,}' % n, b)]


def _elf_pe_info(b: bytes) -> dict:
    info = {}
    if b.startswith(b'\x7fELF') and len(b) > 20:
        info.update(format='ELF', bits=64 if b[4] == 2 else 32, endian='little' if b[5] == 1 else 'big',
                    type={1: 'relocatable', 2: 'executable', 3: 'shared/pie', 4: 'core'}.get(struct.unpack('<H', b[16:18])[0], '?'),
                    machine=struct.unpack('<H', b[18:20])[0])
    elif b.startswith(b'MZ') and len(b) > 0x40:
        off = struct.unpack('<I', b[0x3c:0x40])[0]
        if b[off:off + 4] == b'PE\0\0':
            machine, nsec = struct.unpack('<HH', b[off + 4:off + 8])
            info.update(format='PE', machine=hex(machine), sections=nsec)
    return info


@tool('file_triage', 'Static triage of a sample: hashes, type, entropy, headers, strings, IOCs, suspicious API indicators. Never executes the file.',
      {'path': ('str', True, 'sample path in workspace')}, ('Cipher', 'Sentinel'))
def file_triage(ctx, path):
    p = ctx.path(path)
    if not p.is_file():
        raise ToolError('not a file')
    b = p.read_bytes()[:20_000_000]
    iocs = {k: sorted({m.group().decode('utf-8', 'replace') for m in rx.finditer(b)})[:50] for k, rx in IOC.items()}
    strs = _strings(b)
    ent = round(_entropy(b), 3)
    ind = [s.decode() for s in SUSPICIOUS_API if s in b]
    score = (2 if ent > 7.2 else 0) + min(len(ind), 5) + (1 if iocs['url'] or iocs['ipv4'] else 0)
    return {'path': path, 'size': len(b), 'md5': hashlib.md5(b).hexdigest(), 'sha1': hashlib.sha1(b).hexdigest(),
            'sha256': hashlib.sha256(b).hexdigest(), 'type': _magic(b), 'entropy': ent,
            'packed_or_encrypted_likely': ent > 7.2, 'header': _elf_pe_info(b), 'iocs': iocs,
            'suspicious_indicators': ind, 'string_count': len(strs), 'interesting_strings': strs[:60],
            'triage_score': score, 'classification': 'suspicious' if score >= 4 else ('low-risk' if score <= 1 else 'needs-review'),
            'executed': False}


# ------------------------------------------------------------------ Cipher: YARA
def _yara():
    try:
        import yara
        return yara
    except ImportError:
        raise ToolError('yara-python is not installed')


@tool('yara_generate', 'Generate a YARA rule from distinctive strings of a sample (hash + strings + size bound) and validate it compiles.',
      {'path': ('str', True, 'sample path'), 'rule_name': ('str', True, 'rule identifier'), 'max_strings': ('int', False, 'default 8')},
      ('Cipher',))
def yara_generate(ctx, path, rule_name, max_strings=8):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{2,60}', rule_name):
        raise ToolError('invalid rule name')
    b = ctx.path(path).read_bytes()
    common = {'import', 'return', 'print', 'def ', 'class ', 'self', 'None', 'True', 'False', 'python', '__main__'}
    cands = [s for s in dict.fromkeys(_strings(b, 8)) if not any(c in s for c in common) and len(s) <= 120]
    cands.sort(key=lambda s: (-(len(set(s)) / len(s)) * min(len(s), 40), s))
    chosen = cands[:max_strings]
    if not chosen:
        raise ToolError('no distinctive strings available for a rule')
    esc = lambda s: s.replace('\\', '\\\\').replace('"', '\\"')
    strs = '\n'.join(f'        $s{i} = "{esc(s)}" ascii' for i, s in enumerate(chosen))
    need = max(1, min(len(chosen), (len(chosen) * 2 + 2) // 3))
    text = (f'rule {rule_name}\n{{\n    meta:\n        description = "Generated by Gotham Cipher from sample sha256 {hashlib.sha256(b).hexdigest()}"\n'
            f'        sha256 = "{hashlib.sha256(b).hexdigest()}"\n        purpose = "defensive detection only"\n'
            f'    strings:\n{strs}\n    condition:\n        filesize < {max(len(b) * 4, 4096)} and {need} of ($s*)\n}}\n')
    y = _yara()
    rules = y.compile(source=text)
    self_match = bool(rules.match(data=b))
    out = ctx.workspace / f'{rule_name}.yar'
    out.write_text(text)
    return {'rule_path': out.name, 'rule': text, 'compiles': True, 'matches_source_sample': self_match, 'strings_used': len(chosen)}


@tool('yara_validate', 'Compile a YARA rule and test it against positive and negative sample files.',
      {'rule_path': ('str', True, 'rule file'), 'positive': ('list', True, 'files that MUST match'),
       'negative': ('list', False, 'files that must NOT match')}, ('Cipher', 'Sentinel'))
def yara_validate(ctx, rule_path, positive, negative=None):
    y = _yara()
    try:
        rules = y.compile(source=ctx.path(rule_path).read_text('utf-8'))
    except y.SyntaxError as exc:
        return {'compiles': False, 'error': str(exc)}
    pos = {f: bool(rules.match(data=ctx.path(f).read_bytes())) for f in positive}
    neg = {f: bool(rules.match(data=ctx.path(f).read_bytes())) for f in (negative or [])}
    return {'compiles': True, 'positive': pos, 'negative': neg,
            'true_positives': sum(pos.values()), 'false_negatives': len(pos) - sum(pos.values()),
            'false_positives': sum(neg.values()), 'valid': all(pos.values()) and not any(neg.values())}


@tool('yara_scan', 'Scan every workspace file with a YARA rule file.', {'rule_path': ('str', True, 'rule file'),
      'path': ('str', False, 'dir, default .')}, ('Cipher', 'Sentinel'))
def yara_scan(ctx, rule_path, path='.'):
    y = _yara()
    rules = y.compile(source=ctx.path(rule_path).read_text('utf-8'))
    hits = []
    for p in _walk(ctx.path(path)):
        if p.stat().st_size < 20_000_000 and rules.match(data=p.read_bytes()):
            hits.append(str(p.relative_to(ctx.workspace)))
    return {'matches': hits}


# ------------------------------------------------------------------ Cipher: dynamic behaviour (Python samples only)
HARNESS = r'''
import sys, json, runpy, os
events = []
def hook(event, args):
    if event in ('open','socket.connect','socket.getaddrinfo','subprocess.Popen','os.system','os.exec','os.remove','os.rename',
                 'os.mkdir','shutil.copyfile','import','exec','compile','ctypes.dlopen','os.listdir'):
        if event == 'import' and not str(args[0]).split('.')[0] in ('socket','subprocess','ctypes','base64','urllib','http','ftplib','smtplib','shutil'):
            return
        try: events.append({'event': event, 'args': [repr(a)[:160] for a in args][:4]})
        except Exception: pass
sys.addaudithook(hook)
code = 0
try:
    runpy.run_path(sys.argv[1], run_name='__main__')
except SystemExit as e:
    code = e.code if isinstance(e.code, int) else 0
except BaseException as e:
    events.append({'event': 'uncaught_exception', 'args': [type(e).__name__, str(e)[:200]]})
    code = 1
sys.stderr.write('\nGOTHAM_BEHAVIOR_BEGIN\n' + json.dumps(events[:500]) + '\nGOTHAM_BEHAVIOR_END\n')
sys.exit(code)
'''


@tool('sandbox_behavior', 'Dynamic analysis of an APPROVED inert Python sample: runs it network-less in a locked-down container under an audit-hook '
      'harness and returns behavioural telemetry (file/socket/process/import events).',
      {'path': ('str', True, 'python sample path'), 'timeout': ('int', False, 'seconds, max 30')}, ('Cipher',), risk='high')
def sandbox_behavior(ctx, path, timeout=15):
    p = ctx.path(path)
    if p.suffix != '.py':
        raise ToolError('dynamic analysis is limited to Python samples; use static triage for other formats')
    sbx.ensure_image('gotham-sandbox:latest')
    run_dir = ctx.workspace / '.behavior'
    run_dir.mkdir(exist_ok=True)
    shutil.copyfile(p, run_dir / 'sample.py')
    (run_dir / 'harness.py').write_text(HARNESS)
    r = sbx.run('gotham-sandbox:latest', ['python', '-B', '/work/harness.py', '/work/sample.py'], mount=run_dir, rw=False,
                timeout=ctx.remaining(min(timeout, 30)), memory='128m', cpus='0.5', pids=32)
    m = re.search(r'GOTHAM_BEHAVIOR_BEGIN\n(.*?)\nGOTHAM_BEHAVIOR_END', r['stderr'], re.S)
    events = json.loads(m.group(1)) if m else []
    cats = Counter(e['event'] for e in events)
    verdicts = []
    if cats.get('socket.connect'):
        verdicts.append('attempted network connection (blocked: network=none)')
    if cats.get('subprocess.Popen') or cats.get('os.system') or cats.get('os.exec'):
        verdicts.append('spawned or attempted to spawn processes')
    if cats.get('os.remove') or cats.get('os.rename'):
        verdicts.append('modified/removed files')
    return {**{k: r[k] for k in ('sandbox', 'image', 'network', 'exit_code', 'timed_out', 'container_destroyed', 'elapsed_ms')},
            'stdout': r['stdout'][-2000:], 'event_counts': dict(cats), 'events': events[:100], 'behavior_summary': verdicts,
            'telemetry_complete': bool(m)}
