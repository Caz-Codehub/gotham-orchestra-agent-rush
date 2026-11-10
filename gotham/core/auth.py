"""Authentication and role-based permissions. Tokens come from the environment, never from code."""
from __future__ import annotations
import hashlib
import hmac
import os
import time
from collections import defaultdict
from dataclasses import dataclass
from fastapi import HTTPException, Request

ROLE_PERMS = {
    'batman': {'missions:submit', 'missions:read', 'missions:cancel', 'artifacts:read', 'approvals:decide',
               'audit:read', 'infra:read', 'recovery:run', 'lab:authorize'},
    'operator': {'missions:submit', 'missions:read', 'missions:cancel', 'artifacts:read', 'infra:read'},
    'viewer': {'missions:read', 'artifacts:read', 'infra:read'},
}
ENV_ROLES = (('GOTHAM_BATMAN_TOKEN', 'batman'), ('GOTHAM_OPERATOR_TOKEN', 'operator'),
             ('GOTHAM_ACCESS_TOKEN', 'operator'), ('GOTHAM_VIEWER_TOKEN', 'viewer'))
MIN_TOKEN_LEN = 20
_fail: dict[str, list[float]] = defaultdict(list)


@dataclass(frozen=True)
class Principal:
    role: str
    name: str

    def can(self, perm: str) -> bool:
        return perm in ROLE_PERMS.get(self.role, set())


def weak(token: str) -> bool:
    return len(token) < MIN_TOKEN_LEN or token.lower().startswith(('generate-', 'changeme', 'password'))


def _digest(s: str) -> bytes:
    return hashlib.sha256(s.encode()).digest()


def configured_roles() -> dict[str, bool]:
    return {role: any(os.environ.get(e) and not weak(os.environ[e]) for e, r in ENV_ROLES if r == role)
            for role in ROLE_PERMS}


def authenticate(request: Request) -> Principal:
    ip = request.client.host if request.client else 'unknown'
    now = time.time()
    _fail[ip] = [t for t in _fail[ip] if now - t < 300]
    if len(_fail[ip]) >= 10:
        raise HTTPException(429, 'Too many failed authentications; retry later')
    supplied = ''
    h = request.headers.get('Authorization', '')
    if h.lower().startswith('bearer '):
        supplied = h[7:].strip()
    supplied = supplied or request.headers.get('X-Batman-Token', '') or request.headers.get('X-Gotham-Token', '')
    if not supplied:
        _fail[ip].append(now)
        raise HTTPException(401, 'Authentication required')
    sd = _digest(supplied)
    found = None
    for env, role in ENV_ROLES:  # evaluate all, constant-time per comparison
        tok = os.environ.get(env, '')
        if tok and not weak(tok) and hmac.compare_digest(_digest(tok), sd) and found is None:
            found = Principal(role, env.replace('GOTHAM_', '').replace('_TOKEN', '').lower())
    if not found:
        _fail[ip].append(now)
        raise HTTPException(401, 'Invalid credentials')
    return found


def require(perm: str):
    def dep(request: Request) -> Principal:
        p = authenticate(request)
        if not p.can(perm):
            raise HTTPException(403, f'Role {p.role} lacks permission {perm}')
        return p
    return dep
