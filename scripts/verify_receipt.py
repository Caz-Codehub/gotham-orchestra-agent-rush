#!/usr/bin/env python3
"""Verify local hashes, not signatures or external execution evidence."""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path


def verify(payload):
    if payload.get('mode')=='objective_analysis':
        if 'receipt_sha256' not in payload: return False,'Missing receipt hash'
        canonical={k:v for k,v in payload.items() if k not in ('events','agents','receipt_sha256')}
        computed=hashlib.sha256(json.dumps(canonical,sort_keys=True,ensure_ascii=False,
                    separators=(',',':')).encode('utf-8')).hexdigest()
        if computed!=payload['receipt_sha256']:
            return False,'Objective analysis receipt contents changed'
        return True,'Analysis receipt internally matches; no real-world execution is attested'
    required={'receipt_sha256','candidate_sha256','candidate_code','attempts','candidate_run','status'}
    if not required.issubset(payload): return False,'Missing code-repair receipt fields'
    canonical={k:v for k,v in payload.items() if k not in ('receipt_sha256','candidate_code')}
    computed=hashlib.sha256(json.dumps(canonical,sort_keys=True,default=str).encode('utf-8')).hexdigest()
    if computed != payload['receipt_sha256']: return False,'Code receipt contents changed'
    code=payload.get('candidate_code')
    if code is not None and hashlib.sha256(code.encode('utf-8')).hexdigest()!=payload['candidate_sha256']:
        return False,'Candidate code hash mismatch'
    return True,'Internal SHA-256 hashes match; not an independently signed attestation'


def main():
    if len(sys.argv)!=2:
        print('Usage: python scripts/verify_receipt.py <gotham-receipt.json>',file=sys.stderr)
        return 2
    try: data=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    except (OSError,ValueError) as exc:
        print('Cannot read JSON receipt:',exc,file=sys.stderr);return 2
    ok,message=verify(data)
    print(('PASS: ' if ok else 'FAIL: ')+message)
    return 0 if ok else 1
if __name__=='__main__':sys.exit(main())
