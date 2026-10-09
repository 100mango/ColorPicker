"""Exact capability control: bounded files only; never spawns or signals a process."""
import hashlib,json,os,re,sys
from pathlib import Path
from preflight import read_bounded,assess
from assemble_receipt import assemble,strict
BRANCH='refs/heads/touchcolor-mac-owned-capability'
PARENT='84da71d3526426a6e630887dc88fed59e1edc055'
FILES={'owned_group_capability.c': 'b08500fae8d0efe254a9482954badb8dd16107fc572ebf79a91ca8b9aea02e2a', 'preflight.py': '29fab927bb7f461f72f5dfd677ace369160894e3fabc65a94035a3cb46f53a08', 'assemble_receipt.py': '9ec563e34f589bc7135f045ba75e234181c8436224270f23b11febfa4339358e'}
WORKFLOW='.github/workflows/mac-owned-capability.yml'

def require(value,message):
 if not value:raise ValueError(message)
def identity():
 sha=os.environ.get('GITHUB_SHA','')
 expected={'GITHUB_REPOSITORY':'100mango/ColorPicker','GITHUB_REF':BRANCH,'GITHUB_WORKFLOW_REF':'100mango/ColorPicker/'+WORKFLOW+'@'+BRANCH,'GITHUB_WORKFLOW_SHA':sha,'GITHUB_EVENT_NAME':'push','GITHUB_JOB':'capability','GITHUB_RUN_ATTEMPT':'1'}
 require(re.fullmatch('[0-9a-f]{40}',sha) and all(os.environ.get(k)==v for k,v in expected.items()),'wrong exact capability context')
 return sha

def verify_source():
 sha=identity();root=Path(__file__).resolve().parent
 for name,digest in FILES.items():require(hashlib.sha256(read_bounded(root/name,32768)).hexdigest()==digest,'proposal helper source changed')
 require(read_bounded('build/capability-head.txt',128).decode().strip()==sha,'checked-out SHA differs')
 require(read_bounded('build/capability-parent.txt',128).decode().strip()==sha+' '+PARENT,'not sole actual parent')
 changed=read_bounded('build/capability-changes.txt',2048).decode().splitlines()
 expected={WORKFLOW,*(str(Path('tools/mac-owned-capability')/name) for name in (*FILES,'controller.py'))}
 require(len(changed)==len(expected) and set(changed)==expected,'unexpected product/control path change')
 return {name:digest for name,digest in FILES.items()}

def finish():
 stages={role:{'outcome':os.environ.get(role.upper()+'_OUTCOME','missing'),'exit':os.environ.get(role.upper()+'_EXIT','missing')} for role in ('setup','compile','probe')}
 result={'schema':1,'complete':False,'kind':'public_sdk_synthetic_capability','stages':stages,'expected_parent':PARENT,'source_sha':os.environ.get('GITHUB_SHA',''),'run_id':os.environ.get('GITHUB_RUN_ID',''),'run_attempt':os.environ.get('GITHUB_RUN_ATTEMPT',''),'general_owned_runner_approved':False,'product_qualified':False}
 try:
  hashes=verify_source();meta=strict(read_bounded('build/capability-preflight.json',2048))
  require(meta.get('control_sha')==identity(),'preflight source mismatch')
  reconstructed=assess({'ProductVersion':meta['host_version'],'ProductBuildVersion':meta['host_build']},'\n'.join(meta['xcode_lines'])+'\n',meta['architecture'],meta['system'],meta['python_version'],meta['python_waitid_attributes'],meta['control_sha'])
  require(meta==reconstructed and reconstructed['complete'] is True,'invalid preflight record')
  # All actual step outcomes AND shell-preserved exit codes are required. A
  # successful-looking stdout never erases a nonzero command result.
  statuses_ok=all(row=={'outcome':'success','exit':'0'} for row in stages.values())
  result['preflight']=meta
  try:observed=strict(read_bounded('build/capability-observation.json',4096))
  except (OSError,ValueError):observed={'complete':False,'reason':'missing_or_invalid_actual_observation'}
  combined=strict(assemble(meta,observed,hashes));result['capability_receipt']=combined
  result['complete']=statuses_ok and combined['complete'] is True
  if not statuses_ok:result['reason']='actual_step_failed_skipped_or_exit_missing'
 except (OSError,ValueError,KeyError,TypeError,UnicodeError) as error:
  result['reason']='incomplete_'+type(error).__name__
 raw=(json.dumps(result,sort_keys=True,allow_nan=False)+'\n').encode()
 if len(raw)>8192:
  result.pop('capability_receipt',None);result.pop('preflight',None);result.update(complete=False,reason='receipt_size_exceeded')
  raw=(json.dumps(result,sort_keys=True,allow_nan=False)+'\n').encode()
 require(len(raw)<=8192,'fallback exceeds cap')
 sys.stdout.buffer.write(raw)
 output=os.environ.get('GITHUB_OUTPUT')
 if output:
  with open(output,'a') as stream:stream.write('complete='+str(result['complete']).lower()+'\n')
 return 0 if result['complete'] else 1
if __name__=='__main__':
 if sys.argv[1:]==['verify-source']:verify_source()
 elif sys.argv[1:]==['finish']:raise SystemExit(finish())
 else:raise SystemExit('exact controller action required')
