"""Regression gates for the agreed four-orchestra/12-specialist topology.

These tests validate definitions and the minimal pre-model telemetry boundary;
they do not claim that the newer durable mission engine integrates the orchestras.
"""
import pytest

from gotham.orchestras import ORCHESTRAS, preview, run_orchestra


class RecordingModel:
    configured = True
    provider_name = 'test-model'
    call_count = 0

    def __init__(self, events):
        self.events = events

    def json(self, system, user, *, max_tokens=400):
        self.call_count += 1
        # There must be a committed gate event before each model invocation.
        assert sum(action == 'pre_inference_audit_committed' for action in self.events) >= self.call_count
        assert 'Specter' not in system and 'Specter' not in user
        if 'Provide a JSON object:' in system:
            return {'instructions': {}}
        if 'central Captain Alfred' in system:
            return {'summary': 'Reviewed specialist analysis.', 'priority_actions': ['Confirm evidence']}
        return {'finding': 'Analysis generated from synthetic input.', 'next_steps': ['Review'],
                'tests': ['Verify a fixture'], 'limitations': ['No external execution']}


def test_exact_four_captains_and_twelve_orchestra_scoped_specialist_positions():
    declared = preview()
    assert set(ORCHESTRAS) == {'software', 'research', 'defense', 'lab'}
    assert len(declared) == 4
    assert len({o['captain'] for o in declared}) == 4
    assert sum(len(o['roles']) for o in declared) == 12
    scoped = [(o['id'], r['role']) for o in declared for r in o['roles']]
    assert len(scoped) == len(set(scoped)) == 12
    assert all(len(o['roles']) == 3 for o in declared)
    assert 'Specter' not in repr(declared)


@pytest.mark.parametrize('name', ['software', 'research', 'defense', 'lab'])
def test_orchestra_model_calls_preceded_by_audit_receipt(name):
    events = []
    model = RecordingModel(events)
    goal = 'Prepare a bounded synthetic analysis and show evidence limits'
    scope = 'Owned disposable offline malware analysis laboratory' if name == 'lab' else ''
    result = run_orchestra(name, goal, scope=scope, client=model,
                           telemetry=lambda mid,actor,action,data: events.append(action))
    assert model.call_count == 5
    assert result['status'] == 'analysis_ready'
    assert len(result['worker_reports']) == 3
    assert events.count('pre_inference_audit_committed') == model.call_count
    assert events.count('model_response_received') == model.call_count


def test_audit_failure_blocks_inference():
    class MustNotCall:
        configured = True
        provider_name = 'test-model'
        def json(self, *args, **kwargs):
            raise AssertionError('Model invoked without committed pre-inference audit')

    def failing_audit(mid, actor, action, data):
        if action == 'pre_inference_audit_committed':
            raise IOError('audit sink unavailable')

    with pytest.raises(IOError, match='audit sink unavailable'):
        run_orchestra('software', 'Review a synthetic source file safely',
                      client=MustNotCall(), telemetry=failing_audit)
