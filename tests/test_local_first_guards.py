"""Guard rails to keep Gotham from accidentally renting compute."""
import io
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from gotham.inference import CompatibleInference, NoInference, get_inference_client, is_local_model_name


def test_cloud_aliases_are_not_local_models():
    assert is_local_model_name('qwen2.5:1.5b')
    assert not is_local_model_name('qwen3-coder:480b-cloud')
    assert not is_local_model_name('gemma4:cloud')
    assert not is_local_model_name('')


class FakeResponse(io.BytesIO):
    status = 200
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()


def test_local_provider_rejects_cloud_alias_even_if_listed():
    payload = {'models': [{'name': 'gemma4:cloud', 'model': 'gemma4:cloud', 'size': 2048}]}
    with patch.dict(os.environ, {'GOTHAM_INFERENCE_PROVIDER': 'ollama', 'GOTHAM_OLLAMA_MODEL':'gemma4:cloud'}):
        with patch('urllib.request.urlopen', return_value=FakeResponse(json.dumps(payload).encode())):
            assert isinstance(get_inference_client(), NoInference)


def test_local_provider_requires_downloaded_positive_size_model():
    with patch.dict(os.environ, {'GOTHAM_INFERENCE_PROVIDER': 'ollama', 'GOTHAM_OLLAMA_MODEL':'qwen2.5:1.5b'}):
        with patch('urllib.request.urlopen', return_value=FakeResponse(b'{"models":[{"name":"qwen2.5:1.5b","size":0}]}')):
            assert isinstance(get_inference_client(), NoInference)
        with patch('urllib.request.urlopen', return_value=FakeResponse(b'{"models":[{"name":"qwen2.5:1.5b","size":986000000}]}')):
            assert get_inference_client().provider_name == 'ollama-local'


def test_five_local_calls_use_one_shared_model_gate():
    inside = 0
    peak = 0
    mtx = threading.Lock()

    def fake_urlopen(req, timeout):
        nonlocal inside, peak
        assert req.full_url == 'http://127.0.0.1:11434/api/chat'
        with mtx:
            inside += 1
            peak = max(peak, inside)
        time.sleep(0.01)
        with mtx:
            inside -= 1
        return FakeResponse(b'{"message":{"content":"ok"},"done":true}')

    client = CompatibleInference(endpoint='http://127.0.0.1:11434/api/chat',
                                 model='qwen2.5:1.5b', provider='ollama-local',max_calls=8)
    with patch('urllib.request.urlopen', side_effect=fake_urlopen):
        with ThreadPoolExecutor(max_workers=5) as pool:
            assert list(pool.map(lambda i: client.chat('system', 'hello'), range(5))) == ['ok'] * 5
    assert peak == 1
    assert client.call_count == 5


def test_native_ollama_enforces_context_keep_alive_and_json_mode():
    seen=[]
    def fake_urlopen(req,timeout):
        assert req.full_url=='http://127.0.0.1:11434/api/chat'
        data=json.loads(req.data)
        seen.append((data,timeout))
        return FakeResponse(json.dumps({'message': {'content': json.dumps({'ok': True})}, 'done': True}).encode())
    client=CompatibleInference(endpoint='http://127.0.0.1:11434/api/chat',
                               model='qwen2.5:1.5b',provider='ollama-local')
    with patch.dict(os.environ,{'GOTHAM_LOCAL_CONTEXT_TOKENS':'20000',
                                 'GOTHAM_LOCAL_KEEP_ALIVE':'30s',
                                 'GOTHAM_LOCAL_REQUEST_TIMEOUT_SECONDS':'200'}):
        with patch('urllib.request.urlopen',side_effect=fake_urlopen):
            assert client.json('sys','user')=={'ok':True}
    d,timeout=seen[0]
    assert d['format']=='json'
    assert d['stream'] is False
    assert d['options']['num_ctx']==8192
    assert d['keep_alive']=='30s'
    assert timeout==180
    assert all('key' not in k for k in d)


def test_local_configuration_rejects_invalid_keep_alive_before_request():
    client=CompatibleInference(endpoint='http://127.0.0.1:11434/api/chat',
                               model='qwen2.5:1.5b',provider='ollama-local')
    with patch.dict(os.environ,{'GOTHAM_LOCAL_KEEP_ALIVE':'-1'}):
        with patch('urllib.request.urlopen') as urlopen:
            import pytest
            from gotham.inference import InferenceError
            with pytest.raises(InferenceError): client.chat('system','user')
            urlopen.assert_not_called()


def test_local_keep_alive_is_bounded_for_schoolwork():
    import pytest
    from gotham.inference import InferenceError
    client=CompatibleInference(endpoint='http://127.0.0.1:11434/api/chat',
                               model='qwen2.5:1.5b',provider='ollama-local')
    with patch.dict(os.environ,{'GOTHAM_LOCAL_KEEP_ALIVE':'999m'}):
        with patch('urllib.request.urlopen') as urlopen:
            with pytest.raises(InferenceError,match='5-minute'):
                client.chat('sys','user')
            urlopen.assert_not_called()
