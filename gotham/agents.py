"""Role-constrained mission agents: own goals, tool decisions, state and action evidence."""
from __future__ import annotations
import ast
import hashlib
import re
import time
from dataclasses import dataclass,field
from .inference import CompatibleInference, InferenceError
from .sandbox import run_isolated

@dataclass
class Agent:
    name: str
    rank: str
    goal: str
    tools: tuple[str,...]
    state: str='idle'
    decision_source: str='none'
    actions: list[dict]=field(default_factory=list)

    def snapshot(self):
        return {'name':self.name,'rank':self.rank,'goal':self.goal,
                'state':self.state,'tools':list(self.tools),
                'decision_source':self.decision_source,'actions':self.actions}

WORKERS=[
 ('Scout','Reconnaissance','Understand source, dependencies and risk','inspect_ast','inspect_imports'),
 ('Forge','Engineer','Develop a repair candidate that meets Batman’s goal','propose_patch','describe_patch'),
 ('Oracle','Quality Assurance','Find failures through real sandbox testing','run_baseline','inspect_tests'),
 ('Sentinel','Security','Identify high-risk behaviors and document containment needs','scan_risks','review_boundary'),
 ('Cipher','Strategy','Clarify success conditions and testing priorities','plan_tests','summarize_goal'),
]

def team():
    return [Agent('Alfred','Captain','Coordinate five workers, execute evidence-backed missions and report to Batman',('delegate','execute_candidate','review_evidence'))]+[
            Agent(name,rank,goal,(a,b)) for name,rank,goal,a,b in WORKERS]


def choose_tool(agent:Agent,client:CompatibleInference,context:dict,default:str) -> str:
    if not client.configured:
        agent.decision_source='offline-rule (not an AI decision)'
        return default
    try:
        response=client.json(
            f'You are {agent.name}, an independent tool-using AI worker in Gotham Project. Rank: {agent.rank}. Goal: {agent.goal}. '
            f'You may choose ONLY one tool from {list(agent.tools)}. Choose the highest-value action. Do not execute code in this answer.',
            f'Mission goal: {context["goal"]}\nCode excerpt: {context["code"][:2000]}\nTests excerpt: {context["tests"][:1500]}\n'
            'Return {"tool":"EXACT_TOOL_NAME","reason":"short reason"}.',max_tokens=170)
        action=response.get('tool')
        if action not in agent.tools:
            raise InferenceError('Model selected a disallowed tool')
        agent.decision_source=getattr(client,'provider_name','vultr-serverless-inference')
        return action
    except InferenceError as exc:
        agent.decision_source='vultr-error: '+str(exc)[:90]
        return default


def inspect_ast(code):
    try:
        tree=ast.parse(code)
        funcs=[n.name for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
        imports=[alias.name for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom)) for alias in (n.names if isinstance(n,ast.Import) else [ast.alias(name=n.module or '')])]
        return {'valid_syntax':True,'functions':funcs[:20],'imports':imports[:20],'lines':len(code.splitlines())}
    except SyntaxError as exc:
        return {'valid_syntax':False,'syntax_error':str(exc)[:300],'lines':len(code.splitlines())}


def scan_risks(code):
    """Advisory static scanner; containment is enforced by Docker, not these patterns."""
    patterns={'process spawn':r'\bsubprocess\b|\bos\.system\b',
              'network operations':r'\bsocket\b|\burllib\b|\brequests\b',
              'filesystem writes':r'\bopen\s*\(|\bwrite_text\b|\bunlink\b',
              'dynamic execution':r'\beval\s*\(|\bexec\s*\('}
    return {'advisory_findings':[name for name,pattern in patterns.items() if re.search(pattern,code)],
            'enforced_by':'Docker network-none, read-only, resource limits, nonroot',
            'disclaimer':'Static inspection alone does not prove security'}


def generate_candidate(client:CompatibleInference,goal:str,code:str,tests:str):
    if not client.configured:
        # One explicitly labeled demo fallback only; unrelated arbitrary code is never silently rewritten.
        if 'def add(' in code and 'return a - b' in code and 'add' in goal.lower():
            return code.replace('return a - b','return a + b',1),'sample-rule (not AI)'
        return None,'Vultr inference required for arbitrary repair'
    answer=client.json('You are Forge, a code-repair agent. Return a COMPLETE, corrected Python source file in JSON '
        'with only {"code":"...", "explanation":"..."}. Do not use network, subprocess, third-party packages, secrets or file access. '
        'Respect tests. Keep original API. If fix impossible return {"code":"", "explanation":"reason"}.',
        'Goal: '+goal+'\nOriginal code:\n'+code+'\nTests that must pass:\n'+tests,max_tokens=1600)
    proposal=answer.get('code')
    if not isinstance(proposal,str) or not proposal or len(proposal.encode())>12000:
        return None,'Model supplied no valid patch'
    return proposal,getattr(client,'provider_name','vultr-serverless-inference')


def work(agent:Agent,client:CompatibleInference,mission:dict) -> dict:
    agent.state='working'
    started=time.monotonic()
    default=agent.tools[0]
    selected=choose_tool(agent,client,mission,default)
    try:
        if agent.name=='Scout':
            data=inspect_ast(mission['code'])
        elif agent.name=='Forge':
            proposal,source=generate_candidate(client,mission['goal'],mission['code'],mission['tests'])
            data={'candidate':proposal,'candidate_source':source}
            if selected=='describe_patch':
                data['description']='Proposed candidate will be verified only through isolated tests'
        elif agent.name=='Oracle':
            # Baseline execution is mandatory, even if the model asks to inspect tests first.
            data={'baseline':run_isolated(mission['code'],mission['tests'],timeout=5)}
            if selected=='inspect_tests':
                data.update({'test_assertions':mission['tests'].count('assert'),'test_lines':len(mission['tests'].splitlines())})
        elif agent.name=='Sentinel':
            data=scan_risks(mission['code'])
        else:
            data={'success_criteria':'Candidate must pass provided assertions in isolated Docker; failing baseline recorded',
                  'test_count':mission['tests'].count('assert'),'goal':mission['goal'][:500]}
        agent.actions.append({'tool':selected,'ok':True,'elapsed_ms':round((time.monotonic()-started)*1000)})
        agent.state='completed'
        return data
    except Exception as exc:
        agent.actions.append({'tool':selected,'ok':False,'error':str(exc)[:180]})
        agent.state='blocked'
        return {'error':str(exc)[:350]}
