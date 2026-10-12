"""Fixed-field, <=8KiB diagnostic only. Never proves capture or cleanup success."""
import json,math,re

IDS={'self-test','source','clean-start','host','xcode','runtime-devices','setup-proof','build','create','boot','ready','home','home-summary','home-export','home-proof','device-shutdown','device-delete'}
STAGES={'setup','build','device','home','home-proof','device-cleanup'}
ERRORS={'OwnershipUnknown','TimeoutExpired','PermissionError','OSError','RuntimeError','ValueError','InterruptedError','KeyboardInterrupt','SystemExit','TimeoutError','Other'}
OPS={'spawn','waitid_wnowait','proc_listpids','waitpid_reap','killpg_SIGTERM','killpg_SIGKILL'}
FAULTS=OPS|{op+'_returned_late' for op in OPS}|{'ownership_deadline','terminal_lease_disappeared','unexpected_child_status','unexpected_exit_status','unexpected_signal_status','terminal_lease_changed','invalid_group_members','final_lease_not_terminal','unexpected_reap_result','reap_status_changed','reap_returned_late','cleanup_deadline','transport_permission_denied','owner_handoff_failed'}
STATES={'HELD_LIVE','HELD_TERMINAL','UNKNOWN','REAPED'}
NUMBERS=('step_started_monotonic','native_started_monotonic','native_finished_monotonic','step_work_deadline','step_cleanup_deadline','native_work_deadline','native_cleanup_deadline','operation_started_monotonic','operation_finished_monotonic','operation_deadline')
COUNTERS=('pid','lease_calls','group_calls','reap_calls')
KEYS={'schema','complete','source_sha','run_id','run_attempt','job','lane','step_id','stage','native_id','primary_error','state','operation','ownership_fault','owned_group_cleanup_confirmed',*NUMBERS,*COUNTERS}

def number(value):
 return value if type(value) in (int,float) and 0<=value<=1e13 and math.isfinite(value) else None

def choose(value,allowed):return value if type(value) is str and value in allowed else None

def project(controller):
 active=controller.active_step or {};failure=controller.failure or {};owner=failure.get('owned') or {}
 native=controller.last_native_id;record=controller.records.get(native,{})
 value={'schema':1,'complete':False,**controller.expected,'lane':controller.lane,
  'step_id':choose(active.get('id'),IDS),'stage':choose(active.get('stage'),STAGES),'native_id':choose(native,IDS),
  'primary_error':choose(failure.get('error'),ERRORS) or 'Other','state':choose(owner.get('state'),STATES),
  'operation':choose(owner.get('last_operation'),OPS),'ownership_fault':choose(owner.get('unknown_operation'),FAULTS),'owned_group_cleanup_confirmed':owner.get('owned_group_cleanup_confirmed') is True and owner.get('state')=='REAPED' and owner.get('reap_calls')==1 and type(owner.get('pid')) is int and owner['pid']>0}
 for key in COUNTERS:
  item=owner.get(key);value[key]=item if type(item) is int and 0<=item<=2147483647 else None
 value.update({'step_started_monotonic':number(active.get('started_monotonic')),
  'native_started_monotonic':number(record.get('started_monotonic')),'native_finished_monotonic':number(record.get('finished_monotonic')),
  'step_work_deadline':number(active.get('work_deadline')),'step_cleanup_deadline':number(active.get('cleanup_deadline')),
  'native_work_deadline':number(record.get('work_deadline')),'native_cleanup_deadline':number(record.get('cleanup_deadline')),
  'operation_started_monotonic':number(owner.get('operation_started_monotonic')),
  'operation_finished_monotonic':number(owner.get('operation_finished_monotonic')),
  'operation_deadline':number(owner.get('operation_deadline'))})
 return validate(value,controller.expected,controller.lane)

def validate(value,expected,lane):
 if type(value) is not dict or set(value)!=KEYS:raise ValueError('Diagnostic schema differs')
 if type(value['schema']) is not int or value['schema']!=1 or value['complete'] is not False:raise ValueError('Diagnostic scope differs')
 if lane not in ('iphone17pro','ipad13m5') or value['lane']!=lane:raise ValueError('Diagnostic lane differs')
 for key in ('source_sha','run_id','run_attempt','job'):
  if value[key]!=expected.get(key):raise ValueError('Diagnostic run binding differs')
 if not re.fullmatch('[0-9a-f]{40}',value['source_sha']) or not re.fullmatch('[1-9][0-9]{0,19}',value['run_id']) or value['run_attempt']!='1' or value['job']!='capture-'+lane:raise ValueError('Diagnostic identity malformed')
 for key,allowed in [('step_id',IDS),('native_id',IDS),('stage',STAGES),('primary_error',ERRORS),('state',STATES),('operation',OPS),('ownership_fault',FAULTS)]:
  if value[key] is not None and choose(value[key],allowed) is None:raise ValueError('Non-fixed diagnostic text')
 if type(value['owned_group_cleanup_confirmed']) is not bool:raise ValueError('Diagnostic cleanup type differs')
 for key in NUMBERS:
  if value[key] is not None and number(value[key]) is None:raise ValueError('Diagnostic number invalid')
 for key in COUNTERS:
  if value[key] is not None and (type(value[key]) is not int or not 0<=value[key]<=2147483647):raise ValueError('Diagnostic counter invalid')
 if value['owned_group_cleanup_confirmed'] and not (value['state']=='REAPED' and value['reap_calls']==1 and type(value['pid']) is int and value['pid']>0):raise ValueError('Diagnostic cleanup contradiction')
 if len(encoded(value))>8192:raise ValueError('Diagnostic exceeds8KiB')
 return value

def encoded(value):return (json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
