"""Explicit, bounded model backends: OFFLINE by default, Ollama locally, Vultr opt-in.

Never silently fall back from local to cloud. No user goal, code, or private data is
transmitted to a paid endpoint unless Batman sets BOTH the provider and opt-in flag.
"""
from __future__ import annotations
import json
from contextlib import nullcontext
import os
import re
import threading
import urllib.error
import urllib.request

VULTR_ENDPOINT = 'https://api.vultrinference.com/v1/chat/completions'
OLLAMA_ENDPOINT = 'http://127.0.0.1:11434/api/chat'

# One shared local model, seven roles. Serialize local completions so five workers
# cannot simultaneously exhaust a low-RAM laptop. Worker planning remains parallel.
_LOCAL_INFERENCE_GATE = threading.Lock()
_TRANSPORT_AUDIT_GATE = threading.Lock()

class InferenceError(RuntimeError): pass

class NoInference:
    provider_name = 'offline'
    configured = False
    model = ''
    def json(self, *args, **kwargs):
        raise InferenceError('No model configured. Offline workflows are demonstrations, not AI inference.')

class CompatibleInference:
    """OpenAI-compatible chat, with fixed endpoints to prevent remote URL injection."""
    def __init__(self, *, endpoint, model, key='', provider, max_calls=16):
        self.endpoint = endpoint
        self.model = model
        self.key = key
        self.provider_name = provider
        self.configured = bool(self.model and (provider == 'ollama-local' or key))
        self.max_calls = max(1, min(64, int(max_calls)))
        self._calls = 0
        self._lock = threading.Lock()

    @property
    def call_count(self):
        with self._lock: return self._calls

    def chat(self, system: str, user: str, *, max_tokens: int=400, json_mode: bool=False) -> str:
        if not self.configured:
            raise InferenceError(self.provider_name + ' model is not configured')
        from .model_policy import ModelInputDenied, screen
        from .core.audit import audit_writer
        from .core.config import audit_path
        try:
            system, user, screening = screen(system, user)
        except ModelInputDenied as exc:
            with _TRANSPORT_AUDIT_GATE:
                audit_writer(audit_path()).record(None, None, 'InferenceGateway',
                    'model_input_denied', {'reason': str(exc)[:100],
                                           'provider': self.provider_name[:50]})
            raise InferenceError('Model input denied by pre-inference policy') from exc
        with self._lock:
            if self._calls >= self.max_calls:
                raise InferenceError('Model-call budget exhausted. No further calls issued.')
            self._calls += 1
        local = self.provider_name == 'ollama-local'
        request_data = {'model':self.model,
                        'messages':[{'role':'system','content':system[:5000]},
                                    {'role':'user','content':user[:15000]}]}
        if local:
            # Native local API lets us bound context and release RAM after idle.
            # The Ollama model is loaded ONCE; all Gotham agents share this endpoint.
            raw_ctx = os.environ.get('GOTHAM_LOCAL_CONTEXT_TOKENS','4096')
            raw_timeout = os.environ.get('GOTHAM_LOCAL_REQUEST_TIMEOUT_SECONDS','90')
            try:
                context_size = max(2048, min(8192, int(raw_ctx)))
                request_timeout = max(20, min(180, int(raw_timeout)))
            except ValueError as exc:
                raise InferenceError('Invalid local context or timeout configuration') from exc
            raw_keep = os.environ.get('GOTHAM_LOCAL_KEEP_ALIVE','30s').strip().lower()
            if not re.fullmatch(r'(?:0|[1-9][0-9]{0,2}[sm])',raw_keep):
                raise InferenceError('Local keep-alive must be 0, or 1–300 seconds (e.g. 30s)')
            if raw_keep != '0':
                seconds = int(raw_keep[:-1]) * (60 if raw_keep.endswith('m') else 1)
                if seconds > 300:
                    raise InferenceError('Local keep-alive exceeds the laptop-safe 5-minute cap')
            request_data.update({'stream':False,'format':'json' if json_mode else None,
                                 'options':{'num_ctx':context_size,'num_predict':min(1600,max(80,int(max_tokens))),
                                            'temperature':0.1},'keep_alive':raw_keep})
            if not json_mode: request_data.pop('format')
        else:
            request_data.update({'temperature':0.1,'max_tokens':min(2200,max(80,int(max_tokens)))})
            request_timeout = 65
        # Final mandatory audit gate immediately before transport. This applies
        # to legacy code paths too, not just the v4 runtime and orchestral DAG.
        # It records hashes/metadata only; no private auditor identity enters prompts.
        import hashlib
        # Serialize short journal initialization+append: concurrent local
        # completions otherwise race on SQLite journal_mode=WAL setup.
        # Never hold this lock during network inference.
        with _TRANSPORT_AUDIT_GATE:
            audit_writer(audit_path()).record(
                None, None, 'InferenceGateway', 'pre_model_transport',
                {'provider': self.provider_name[:50], 'model': self.model[:80],
                 'system_sha256': hashlib.sha256(system.encode()).hexdigest(),
                 'input_sha256': hashlib.sha256(user.encode()).hexdigest(),
                 'local': local, 'input_screening': screening})
        headers = {'Content-Type':'application/json'}
        if self.key: headers['Authorization']='Bearer '+self.key
        req = urllib.request.Request(self.endpoint,json.dumps(request_data).encode(),headers=headers,method='POST')
        try:
            # The gate is shared by every Ollama client in this Gotham process,
            # including Specter's optional model-based triage. No duplicated loads.
            gate = _LOCAL_INFERENCE_GATE if self.provider_name == 'ollama-local' else nullcontext()
            with gate:
                with urllib.request.urlopen(req,timeout=request_timeout) as response:
                    data=json.load(response)
            raw = data['message']['content'] if local else data['choices'][0]['message']['content']
            if not isinstance(raw,str) or not raw.strip():
                raise ValueError('Empty or non-text completion')
            return raw.strip()
        except (urllib.error.URLError,KeyError,ValueError,TimeoutError,OSError) as exc:
            raise InferenceError(f'{self.provider_name} inference unavailable ({type(exc).__name__})') from exc

    def json(self, system: str, user: str, *, max_tokens: int=450) -> dict:
        answer=self.chat(system+' Return one valid JSON object. No markdown.',user,max_tokens=max_tokens,json_mode=True)
        answer=re.sub(r'^```(?:json)?\s*|\s*```$','',answer.strip())
        try:
            value=json.loads(answer)
            if not isinstance(value,dict): raise ValueError('Expected JSON object')
            return value
        except ValueError as exc:
            # Some small local models wrap JSON in prose; extract a single object conservatively.
            start=answer.find('{'); end=answer.rfind('}')
            if start>=0 and end>start:
                try:
                    value=json.loads(answer[start:end+1])
                    if isinstance(value,dict): return value
                except ValueError: pass
            raise InferenceError('Model did not provide valid JSON') from exc

class VultrInference(CompatibleInference):
    def __init__(self):
        # This class is retained for backward compatibility; the factory is what
        # controls whether any billable inference can actually be reached.
        super().__init__(endpoint=VULTR_ENDPOINT,
              model=os.environ.get('VULTR_INFERENCE_MODEL',''),
              key=os.environ.get('VULTR_INFERENCE_API_KEY',''),
              provider='vultr-serverless-inference',
              max_calls=os.environ.get('GOTHAM_MAX_MODEL_CALLS','12'))

class OllamaInference(CompatibleInference):
    def __init__(self):
        super().__init__(endpoint=OLLAMA_ENDPOINT,
              model=os.environ.get('GOTHAM_OLLAMA_MODEL','qwen2.5:1.5b'),
              provider='ollama-local',
              max_calls=os.environ.get('GOTHAM_MAX_MODEL_CALLS','16'))


def is_local_model_name(model: str) -> bool:
    """Reject Ollama cloud shortcuts, which can route through the local server."""
    name = model.strip().lower()
    return bool(name) and not name.endswith(':cloud') and not name.endswith('-cloud')


def get_inference_client():
    """$0 by default. Only local Ollama or explicit no-model; cloud is double-opt-in."""
    provider=os.environ.get('GOTHAM_INFERENCE_PROVIDER','none').strip().lower()
    if provider == 'ollama':
        try:
            with urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=1.5) as response:
                models=json.load(response).get('models',[]) if response.status == 200 else []
            selected=os.environ.get('GOTHAM_OLLAMA_MODEL','qwen2.5:1.5b')
            if not is_local_model_name(selected):
                return NoInference()
            if any((item.get('name') == selected or item.get('model') == selected)
                    and int(item.get('size', 0) or 0) > 0 for item in models):
                return OllamaInference()
        except (OSError,urllib.error.URLError,TimeoutError):
            pass
        return NoInference()
    if provider == 'vultr':
        if os.environ.get('GOTHAM_ALLOW_PAID_INFERENCE','') != 'I_ACCEPT_POTENTIAL_CHARGES':
            return NoInference()
        return VultrInference()
    return NoInference()
