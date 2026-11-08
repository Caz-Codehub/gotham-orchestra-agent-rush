"""Run: python -m unittest discover -s tests -p 'test_clocked_gateway.py'"""
import unittest
from clocked_gateway import preflight

class Fake:
    def __init__(self, injection=None, pii=None, script=None):
        self._injection = injection if injection is not None else {"verdict": "clean", "injection": False}
        self._pii = pii if pii is not None else {"anonymized_text": "Contact [EMAIL]"}
        self._script = script if script is not None else {"verdict": "safe"}
    def injection(self, **kwargs): return self._injection
    def pii(self, **kwargs): return self._pii
    def script(self, **kwargs): return self._script

class ClockedGatewayTests(unittest.TestCase):
    def test_clean_text_is_sanitized(self):
        result = preflight("Contact alex@example.org", client=Fake())
        self.assertTrue(result.allowed)
        self.assertEqual(result.sanitized_text, "Contact [EMAIL]")
    def test_injection_blocks(self):
        result = preflight("malicious", client=Fake(injection={"verdict": "blocked", "injection": True}))
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "guard_not_cleared")
    def test_script_blocks(self):
        result = preflight("Task", script="unsafe", client=Fake(script={"verdict": "dangerous"}))
        self.assertFalse(result.allowed)
    def test_provider_error_blocks(self):
        class Broken:
            def injection(self, **kwargs): raise RuntimeError("secret-key")
        result = preflight("Task", client=Broken())
        self.assertFalse(result.allowed)
        self.assertNotIn("secret-key", repr(result.to_dict()))
    def test_unknown_injection_blocks(self):
        self.assertFalse(preflight("Task", client=Fake(injection={})).allowed)
    def test_missing_redaction_blocks(self):
        self.assertFalse(preflight("Task", client=Fake(pii={})).allowed)
    def test_empty_input_blocks(self):
        self.assertFalse(preflight(" ", client=Fake()).allowed)

if __name__ == "__main__":
    unittest.main()
