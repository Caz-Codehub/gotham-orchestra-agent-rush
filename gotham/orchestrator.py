"""Gotham operations: Batman -> Captain Alfred -> five workers; Specter observes independently."""
from __future__ import annotations
import hashlib
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from .agents import team, work, scan_risks, inspect_ast
from .inference import get_inference_client, InferenceError
from .sandbox import run_isolated


def digest(data):
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def run_mission(goal:str, code:str, tests:str, *, client=None, telemetry=None) -> dict:
    if not 4<=len(goal.strip())<=500: raise ValueError('Goal must be 4-500 characters')
    if not code.strip() or len(code.encode())>12000: raise ValueError('Code must be nonempty, under 12 KB')
    if not tests.strip() or len(tests.encode())>6000: raise ValueError('Tests must be nonempty, under 6 KB')
    client=client or get_inference_client()
    agents=team()
    alfred=agents[0]
    workers=agents[1:]
    mission={'goal':goal.strip(),'code':code,'tests':tests}
    mission_id=str(uuid.uuid4())
    started=time.monotonic()
    class MissionEvents(list):
        def append(self, event):
            super().append(event)
            if telemetry is not None:
                actor = event.get('agent') or ('Batman' if event.get('phase')=='user' else 'Alfred')
                action = event.get('action','unclassified')
                # Independent observer gets metadata only, never code, prompts or raw results.
                metadata = {k:v for k,v in event.items() if k not in ('phase','agent','action','workers','goal')}
                telemetry(mission_id, actor, action, metadata)
    events=MissionEvents()
    events.append({'phase':'user','action':'mission_received','goal':goal[:200]})
    alfred.state='delegating'
    alfred.decision_source='policy-coordination'
    alfred.actions.append({'tool':'delegate','ok':True,'worker_count':5})
    events.append({'phase':'alfred','action':'alfred_tool','tool':'delegate'})
    events.append({'phase':'alfred','action':'parallel_delegation','workers':[a.name for a in workers], 'worker_count':len(workers)})
    outputs={}
    with ThreadPoolExecutor(max_workers=5) as pool:
        future_map={pool.submit(work,agent,client,mission):agent for agent in workers}
        for future in as_completed(future_map):
            agent=future_map[future]
            outputs[agent.name]=future.result()
            events.append({'phase':'worker','agent':agent.name,'action':'worker_finished',
                           'state':agent.state,'tool':agent.actions[-1]['tool'], 'source':agent.decision_source})
            if agent.name=='Oracle' and isinstance(outputs[agent.name].get('baseline'),dict):
                baseline_log=outputs[agent.name]['baseline']
                events.append({'phase':'audit_evidence','agent':'Oracle','action':'baseline_result',
                               **{k:baseline_log.get(k) for k in ('passed','sandbox','network','container_destroyed','timed_out','exit_code')}})
    candidate=outputs.get('Forge',{}).get('candidate')
    candidate_source=outputs.get('Forge',{}).get('candidate_source')
    candidate_risks=None
    tested=None
    attempts=[]
    prohibited_changes={'network operations','process spawn','dynamic execution'}
    # Hard maximum: one model repair retry following a failed/blocked candidate.
    # No local fallback or additional billable call is made when inference is absent.
    max_attempts=2 if client.configured else 1
    for attempt_no in range(1,max_attempts+1):
        if not candidate:
            events.append({'phase':'alfred','action':'no_candidate','reason':candidate_source or 'unavailable'})
            break
        candidate_risks=scan_risks(candidate)
        checked_syntax=inspect_ast(candidate)
        blocked_findings=sorted(prohibited_changes.intersection(candidate_risks['advisory_findings']))
        if blocked_findings:
            tested={'passed':False,'error':'Restricted proposed behavior: '+', '.join(blocked_findings)}
            events.append({'phase':'sentinel','action':'candidate_rejected','attempt':attempt_no,'reason':tested['error']})
        elif not checked_syntax['valid_syntax']:
            tested={'passed':False,'error':'Generated patch failed syntax validation'}
            events.append({'phase':'sentinel','action':'candidate_rejected','attempt':attempt_no,'reason':tested['error']})
        else:
            alfred.state='executing'
            try:
                tested=run_isolated(candidate,tests,timeout=5)
                alfred.actions.append({'tool':'execute_candidate','attempt':attempt_no,'ok':True,'passed':tested['passed']})
                events.append({'phase':'alfred','action':'alfred_tool','tool':'execute_candidate'})
                events.append({'phase':'alfred','action':'sandbox_result','attempt':attempt_no,
                               **{k:tested.get(k) for k in ('passed','sandbox','network','container_destroyed','timed_out','exit_code')}})
            except Exception as exc:
                tested={'passed':False,'error':str(exc)[:300]}
                alfred.actions.append({'tool':'execute_candidate','attempt':attempt_no,'ok':False,'error':str(exc)[:180]})
                events.append({'phase':'alfred','action':'candidate_blocked','attempt':attempt_no,'reason':str(exc)[:180]})
        attempts.append({'number':attempt_no,'candidate_sha256':digest(candidate),'source':candidate_source,
                         'passed':bool(tested and tested.get('passed')),
                         'sandbox':tested.get('sandbox') if tested else None,
                         'detail':str(tested.get('error') or tested.get('output') or '')[:600] if tested else ''})
        if tested and tested.get('passed'):
            break
        if attempt_no>=max_attempts or not client.configured:
            break
        # A failure is evidence to feed back to Forge. This is the only retry.
        try:
            reply=client.json(
                'You are Forge repairing a failed Python patch. Produce a COMPLETE corrected source file as strict JSON '
                '{"code":"...","explanation":"..."}. Do not use subprocess, network, dynamic execution or files.',
                json.dumps({'goal':goal,'failed_candidate':candidate,'tests':tests,
                            'failure':{'error':tested.get('error'),'output':tested.get('output'),
                                       'exit_code':tested.get('exit_code')}},default=str)[:12000],
                max_tokens=1600)
            proposed=reply.get('code')
            if not isinstance(proposed,str) or not proposed.strip() or len(proposed.encode('utf-8'))>12000:
                raise InferenceError('Retry did not return a valid source file')
            candidate=proposed
            candidate_source=getattr(client,'provider_name','vultr-serverless-inference')+' (retry)'
            events.append({'phase':'forge','action':'repair_retry','attempt':attempt_no+1})
        except InferenceError as exc:
            events.append({'phase':'forge','action':'retry_unavailable','reason':str(exc)[:180]})
            break
    alfred.state='completed' if tested and tested.get('passed') else 'blocked'
    # Hard evidence gates supersede all model opinions; optional model review cannot override failure.
    baseline=outputs.get('Oracle',{}).get('baseline')
    def has_docker_evidence(result, source_code):
        return bool(isinstance(result,dict) and result.get('sandbox')=='docker'
                    and result.get('network')=='none' and result.get('container_destroyed') is True
                    and result.get('timed_out') is False
                    and result.get('code_sha256')==digest(source_code))
    real_candidate_pass=bool(has_docker_evidence(tested,candidate) and tested.get('passed')
                             and tested.get('exit_code')==0)
    real_baseline=has_docker_evidence(baseline,code)
    approval=bool(real_candidate_pass and real_baseline)
    reviewer_comment='Verification requires real Docker executions and passing tests.'
    if client.configured and real_candidate_pass and real_baseline:
        try:
            review=client.json('You are Captain Alfred, the coordinating AI for five specialist workers. Assess execution evidence and technical risk. '
              'Give honest findings, never invent results. Respond {"assessment":"brief text","recommend_approval":boolean}.',
              json.dumps({'goal':goal,'baseline':baseline,'candidate':tested,'security':outputs.get('Sentinel')},default=str)[:7000],max_tokens=220)
            reviewer_comment=str(review.get('assessment',''))[:500] or reviewer_comment
            alfred.decision_source=getattr(client,'provider_name','vultr-serverless-inference')
            if review.get('recommend_approval') is False:
                approval=False
        except InferenceError as exc:
            alfred.decision_source='model_error: '+str(exc)[:80]
    else:
        alfred.decision_source='offline-evidence-policy (not AI)'
    alfred.state='verified' if approval else 'withheld'
    alfred.actions.append({'tool':'review_evidence','ok':True,'verified':approval})
    events.append({'phase':'alfred','action':'alfred_tool','tool':'review_evidence'})
    events.append({'phase':'alfred','action':'verified' if approval else 'withheld','reason':reviewer_comment})
    events.append({'phase':'alfred','action':'mission_finished','approved':approval,
                   'verified_evidence':bool(real_candidate_pass and real_baseline),
                   'status':'verified' if approval else 'not_verified'})
    answer={'mission_id':mission_id, 'project':'Gotham Project / Agent Rush 2026',
        'approval':approval, 'status':'verified' if approval else 'not_verified',
        'goal':goal,'inference':(getattr(client,'provider_name','vultr-serverless-inference') if candidate_source and (candidate_source.startswith('vultr-serverless-inference') or candidate_source.startswith('ollama-local')) else ('NO VULTR MODEL PATCH - NOT CONTEST COMPLIANT' if client.configured else 'OFFLINE RULES - NOT CONTEST COMPLIANT')),
        'baseline':baseline,'candidate_run':tested,
        'candidate_code':candidate, 'candidate_source':candidate_source, 'attempts':attempts,
        'security_scan':outputs.get('Sentinel'), 'candidate_security_scan':candidate_risks,
        'insights':{'scout':outputs.get('Scout'), 'strategy':outputs.get('Cipher')},
        'agents':[a.snapshot() for a in agents], 'events':events,
        'input_sha256':digest(code), 'tests_sha256':digest(tests),
        'candidate_sha256':digest(candidate) if candidate else None,
        'elapsed_ms':round((time.monotonic()-started)*1000)}
    receipt=json.dumps({k:v for k,v in answer.items() if k!='candidate_code'},sort_keys=True,default=str)
    answer['receipt_sha256']=digest(receipt)
    return answer
