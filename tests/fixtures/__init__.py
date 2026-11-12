"""Deliberate, harmless fixtures used by acceptance tests."""
import base64

BUGGY_PROJECT = {
    'calc.py': 'def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n',
    'test_calc.py': 'from calc import add, mul\n\n\ndef test_add():\n    assert add(2, 3) == 5\n    assert add(-4, 7) == 3\n\n\ndef test_mul():\n    assert mul(3, 4) == 12\n',
}
FIX_PATCH = {'calc.py': 'def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n'}

# Deliberately weak code for Sentinel to find (never executed)
WEAK_PROJECT = {
    'app.py': ('import sqlite3, subprocess, hashlib\n\nDB_PASSWORD = "hunter2-prod-password"\n\n'
               'def find(conn, name):\n    return conn.execute("SELECT * FROM users WHERE name=\'%s\'" % name).fetchall()\n\n'
               'def run(cmd):\n    return subprocess.run(cmd, shell=True)\n\n'
               'def calc(expr):\n    return eval(expr)\n\n'
               'def digest(x):\n    return hashlib.md5(x.encode()).hexdigest()\n'),
    'requirements.txt': 'requests==2.19.0\n',
    'Dockerfile': 'FROM python:latest\nCOPY . /app\nCMD ["python","/app/app.py"]\n',
    'config.py': 'API_KEY = "sk-live-0123456789abcdef0123"\n',
}
WEAK_EXPECTED = ['gotham.python.eval-exec', 'gotham.python.subprocess-shell-true', 'gotham.python.sql-string-format',
                 'gotham.python.hardcoded-secret', 'gotham.python.weak-hash']

# Inert research sample: harmless script with suspicious-LOOKING strings and benign probes (connect to .invalid, write to /tmp)
INERT_SAMPLE = '''# INERT TEST SAMPLE - emulates the *shape* of suspicious behaviour; does nothing harmful.
import socket, os, base64
C2_URL = "http://beacon-test.example.invalid/gate.php"
CAMPAIGN_ID = "GOTHAM-INERT-SAMPLE-7731-ALPHA"
MUTEX_NAME = "Global\\\\GothamInertMutex-9f31c"
def beacon():
    try:
        s = socket.create_connection(("192.0.2.1", 4444), timeout=1)   # TEST-NET-1, unroutable, blocked by sandbox anyway
    except OSError:
        pass
def drop():
    with open("/tmp/gotham_inert_marker.txt", "w") as f:
        f.write(base64.b64encode(b"inert marker").decode())
beacon(); drop()
print("inert sample finished")
'''

NOTEBOOK_CELLS = [
    {'type': 'markdown', 'source': '# Gotham Oracle statistical check'},
    {'type': 'code', 'source': 'import numpy as np, json\nrng = np.random.RandomState(7)\na = rng.normal(0.0, 1.0, 500)\nb = rng.normal(0.4, 1.0, 500)\nprint("mean_diff", round(float(b.mean()-a.mean()), 4))'},
    {'type': 'code', 'source': 'from scipy import stats\nt, p = stats.ttest_ind(a, b)\nresult = {"t": float(t), "p": float(p)}\njson.dump(result, open("stats.json", "w"))\nprint("p_value", round(float(p), 8))\nassert p < 0.05'},
]

AUTH_LOG = '\n'.join(
    [f'Nov 10 10:0{i%10}:00 host sshd[1]: Failed password for root from 203.0.113.9 port 22' for i in range(8)]
    + ['Nov 10 10:20:00 host sshd[1]: Accepted password for root from 203.0.113.9 port 22']
    + ['Nov 10 10:21:00 host sshd[1]: Failed password for alice from 198.51.100.4 port 22'] * 2) + '\n'
