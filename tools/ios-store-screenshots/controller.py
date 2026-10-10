"""CLOSED original922 capture controller; fixed two selectors, one owned Session."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import argparse,hashlib,json,os,re,subprocess,time,uuid
import io_boundary as io
import source_guard as source
import owned_mac_process as owned
import self_test,commands,evidence,source_helpers
import capture_contract as contract
from budget import Ledger

def require(value,message):
 if not value:raise ValueError(message)

class Controller:
 def __init__(self,lane,*,session=None,clock=time.monotonic,wall=time.time):
  self.lane,self.clock,self.wall=lane,clock,wall
  require(all(os.environ.get(k)==v for k,v in {'BOOTSTRAP_OUTCOME':'success','COMPILE_OUTCOME':'success','COMPILE_EXIT':'0'}.items()),'Actual compile/bootstrap failed')
  self.binding=source.check(lane);require(source.tools_manifest()['READY'] is True,'CLOSED capture route')
  self.plan=commands.stages(lane);self.ledger=Ledger(float(os.environ['TOUCHCOLOR_JOB_STARTED_MONOTONIC']),self.plan,epoch=float(os.environ['TOUCHCOLOR_JOB_STARTED_EPOCH']),clock=clock,wall=wall)
  self.session=session or owned.Session(owned.PublicMac(io.REPO/'build/store-owned-public.dylib'))
  self.work=io.REPO/'build/store-capture';self.derived=self.work/'derived';self.records={};self.logs={};self.results={};self.images={};self.exported={};self.source=None;self.host=None;self.device=None;self.home=False;self.photo=False;self.failure=None;self.cleaned=False
  self.expected={'source_sha':os.environ['GITHUB_SHA'],'run_id':os.environ['GITHUB_RUN_ID'],'run_attempt':os.environ['GITHUB_RUN_ATTEMPT'],'job':os.environ['GITHUB_JOB']}
  io.DEADLINE=min(self.ledger.phase_end('work'),self.ledger.start+240)
  require(not self.work.exists() and not evidence.UPLOAD.exists(),'Fresh owned result/output roots required')
  io.mkdir(self.work);io.mkdir(evidence.UPLOAD)
 def put_json(self,name,value):evidence.put(name,io.encoded(value))
 def run_native(self,step,allocation,argv,*,allow_failure=False):
  self.ledger.recheck(allocation,step['cleanup']);began=self.wall();observed=bytearray()
  def consume(index,raw):observed.extend(raw)
  try:
   self.ledger.recheck(allocation,step['cleanup'])
   result=self.session.run(argv,work_deadline=allocation['work_deadline'],cleanup_deadline=allocation['cleanup_deadline'],maximum_bytes=2000000,text=False,stderr=subprocess.STDOUT,consume=consume)
  except BaseException as error:
   self.records[step['id']]={**allocation,**self.expected,'argv':argv,'exit':None,'started_epoch':began,'finished_epoch':self.wall(),'finished_monotonic':self.clock(),'error':type(error).__name__,'reason':str(error)[:500],'owned':getattr(error,'owned_receipt',None),'log':{'bytes':len(observed),'sha256':io.digest(bytes(observed))}}
   self.logs[step['id']]=bytes(observed);raise
  raw=result.stdout;record={**allocation,**self.expected,'argv':argv,'exit':result.returncode,'started_epoch':began,'finished_epoch':self.wall(),'finished_monotonic':self.clock(),'owned':result.owned_receipt,'log':{'bytes':len(raw),'sha256':io.digest(raw)}}
  self.records[step['id']]=record;self.logs[step['id']]=raw
  if step['id'] in ('home','photo'):print(raw.decode('utf-8'),end='',flush=True)
  if result.returncode and not allow_failure:
   error=RuntimeError('Native command '+step['id']+' exited '+str(result.returncode));error.owned_receipt=result.owned_receipt;error.cleanup_confirmed=True;raise error
  return raw
 def local(self,step,allocation):
  name=step['id'];end=allocation['work_deadline']
  if name=='setup-proof':
   require(all(len(self.logs[key])<=65536 for key in ('source','host','xcode')),'Setup stdout exceeds retained reader cap')
   parts=self.logs['source'].decode().strip().splitlines();require(len(parts)==3 and parts[0]==self.expected['source_sha'] and parts[2]==contract.PRODUCT and re.fullmatch('[0-9a-f]{40}',parts[1]),'Expected actual control with sole fixed922 parent')
   require(self.logs['clean-start']==b'','Tracked/untracked source dirty')
   self.source={'sha':parts[0],'tree':parts[1],'parent':parts[2],'product':contract.PRODUCT,'protected_files':464}
   host=dict(re.findall(r'^(ProductName|ProductVersion|BuildVersion):\s*(.*?)\s*$',self.logs['host'].decode(),re.M));pair=(host.get('ProductVersion'),host.get('BuildVersion'))
   xcode=self.logs['xcode'].decode().strip().splitlines();require(pair in {('27.0','26A428'),('27.0.1','26A434')} and xcode==['Xcode 27.0','Build version 27A266a'],'Exact host/toolchain pair differs')
   self.host={'version':pair[0],'build':pair[1],'xcode':xcode}
   require(len(self.logs['runtime-devices'])<=1048576,'Runtime metadata exceeds retained reader cap')
   metadata=json.loads(self.logs['runtime-devices']);self.mapping=contract.choose_device(metadata['runtimes'],metadata['devicetypes'],self.lane);self.existing_devices=contract.existing_device_ids(metadata)
   self.put_json('source.json',self.source);self.put_json('host.json',self.host);evidence.put('runtime-devices.json',self.logs['runtime-devices'])
   for key in ('source','host','xcode'):evidence.put(key+'.log',self.logs[key])
   raw=source_helpers.fixture();self.fixture=self.work/'six-colors.png';io.write(self.fixture,raw,maximum=65536);evidence.put('six-colors.png',raw);self.put_json('fixture.json',{'bytes':len(raw),'sha256':io.digest(raw),'source':'exact922 original_design_gate.fixture_png'})
  elif name in ('home-proof','photo-proof'):
   role=name.split('-')[0];record=self.records[role];summary=json.loads(self.logs[role+'-summary']);contract.bind_summary(summary,record,self.device,self.lane);contract.bind_cases(self.logs[role],role)
   export=self.work/(role+'-export');raw_manifest=io.read(export/'manifest.json',1048576);manifest=json.loads(raw_manifest)
   selected=evidence.images_from_manifest(manifest,role,summary,self.device,self.lane,lambda name:io.read(export/name,2*1024*1024),end)
   # First retain original raw proof files; declaration only after every copy.
   evidence.put(role+'-summary.json',self.logs[role+'-summary']);evidence.put(role+'-attachments.json',raw_manifest);evidence.put(role+'.log',self.logs[role]);self.put_json(role+'-command.json',record)
   for title,value in selected.items():
    file=title+'.png';evidence.put(file,value['raw']);self.images[title]={'path':file,'proof':value['proof'],'attachment':value['attachment'],'group':value['group']};self.exported[value['attachment']['exportedFileName']]=file
   if role=='home':self.home=True
   else:self.photo=True
  else:raise ValueError('Unknown pure step')
 def argv(self,name):
  if name=='source':return ['/usr/bin/git','show','-s','--format=%H%n%T%n%P','HEAD']
  if name=='clean-start':return ['/usr/bin/git','status','--porcelain','--untracked-files=all']
  if name=='host':return ['/usr/bin/sw_vers']
  if name=='xcode':return ['/usr/bin/xcodebuild','-version']
  if name=='runtime-devices':return ['/usr/bin/xcrun','simctl','list','--json']
  if name=='build':return commands.build(self.derived)
  if name=='create':
   self.owned_name='TouchColor Store '+self.lane+' '+self.expected['source_sha']+' '+self.expected['run_id']+'-'+self.expected['run_attempt']
   return ['/usr/bin/xcrun','simctl','create',self.owned_name,self.mapping['device_type'],self.mapping['runtime']]
  if name=='boot':return ['/usr/bin/xcrun','simctl','boot',self.device['uuid']]
  if name=='ready':return ['/usr/bin/xcrun','simctl','bootstatus',self.device['uuid'],'-b']
  if name in ('home','photo'):
   result=self.work/(name+'.xcresult');require(not result.exists(),'Fresh exact result required');self.results[name]=str(result)
   return commands.test(name,self.device['uuid'],self.derived,result)
  if name.endswith('-summary'):return ['/usr/bin/xcrun','xcresulttool','get','test-results','summary','--path',self.results[name.split('-')[0]]]
  if name.endswith('-export'):
   require(not (self.work/name).exists(),'Fresh exact export required')
   return ['/usr/bin/xcrun','xcresulttool','export','attachments','--path',self.results[name.split('-')[0]],'--output-path',str(self.work/name)]
  if name=='seed':
   raw=io.read(self.fixture,1675);require(len(raw)==1675 and io.digest(raw)=='6190ef70ec7da8b038c026cb8ffc0fc03b40a67ebdc6a382ee68b502135874ba','Actual import fixture changed before addmedia')
   return ['/usr/bin/xcrun','simctl','addmedia',self.device['uuid'],str(self.fixture)]
  raise ValueError('Unknown native step')
 def execute(self):
  for index,stage in enumerate(self.plan):
   self.ledger.enter(index)
   for step in stage['commands']:
    allocation=self.ledger.admit(step);io.DEADLINE=allocation['cleanup_deadline']
    if step['local']:
     io.DEADLINE=allocation['work_deadline'];self.local(step,allocation);self.ledger.check_local(allocation);continue
    if step['id']=='self-test':
     self.ledger.recheck(allocation,20);proof=self_test.run(self.session,work_deadline=allocation['work_deadline'],cleanup_deadline=allocation['cleanup_deadline']);self.put_json('self-test.json',proof);continue
    argv=self.argv(step['id']);raw=self.run_native(step,allocation,argv)
    if step['id'] in ('home','photo'):
     # Failed/foreign case proof cannot dispatch any new native exporter.
     io.DEADLINE=allocation['work_deadline'];contract.bind_cases(raw,step['id']);self.ledger.check_local(allocation)
    elif step['id'] in ('home-summary','photo-summary'):
     # Bind exact method result/device/time before attachment export.
     io.DEADLINE=allocation['work_deadline'];role=step['id'].split('-')[0]
     require(len(raw)<=256000,'Selected summary exceeds retained reader cap')
     contract.bind_summary(json.loads(raw),self.records[role],self.device,self.lane);self.ledger.check_local(allocation)
    elif step['id']=='create':
     device=raw.decode().strip();require(str(uuid.UUID(device)).upper()==device and device not in self.existing_devices,'Unknown or pre-existing created UUID');self.device={'uuid':device,'owned_name':self.owned_name,'mapping':self.mapping};self.put_json('device.json',self.device)
    elif step['id']=='ready':
     self.put_json('bootstatus.json',source_helpers.bootstatus(raw.decode(),{'name':self.owned_name,'device':self.device['uuid']}));evidence.put('bootstatus.log',raw)
   self.ledger.finish_stage()
  self.cleanup_device()
 def cleanup_device(self):
  # Tail-only commands use the same Session; never called from an error handler.
  self.ledger.refresh();end=min(self.clock()+100,self.ledger.phase_end('evidence'));require(self.clock()+98<=end,'No complete owned-device cleanup allowance')
  for index,action in enumerate(('shutdown','delete')):
   now=self.clock();self.ledger.refresh();deadline=min(now+49,end-(1-index)*49,self.ledger.phase_end('evidence')-(1-index)*49)
   require(deadline-now>=49 and self.session.fault is None,'Cleanup lost its original reserve')
   argv=['/usr/bin/xcrun','simctl',action,self.device['uuid']];began=self.wall()
   self.ledger.refresh();deadline=min(deadline,self.ledger.phase_end('evidence')-(1-index)*49)
   require(self.clock()<deadline-20,'Cleanup original dispatch cutoff expired')
   try:result=self.session.run(argv,work_deadline=deadline-20,cleanup_deadline=deadline,maximum_bytes=65536,text=False)
   except BaseException as error:
    self.records['device-'+action]={**self.expected,'argv':argv,'started_epoch':began,'finished_epoch':self.wall(),'work_deadline':deadline-20,'cleanup_deadline':deadline,'exit':None,'error':type(error).__name__,'owned':getattr(error,'owned_receipt',None)}
    raise
   self.records['device-'+action]={**self.expected,'argv':argv,'started_epoch':began,'finished_epoch':self.wall(),'finished_monotonic':self.clock(),'work_deadline':deadline-20,'cleanup_deadline':deadline,'exit':result.returncode,'owned':result.owned_receipt,'log':{'bytes':len(result.stdout),'sha256':io.digest(result.stdout)}}
   require(result.returncode==0,'Owned simulator cleanup failed: '+action+' exit '+str(result.returncode))
  self.cleaned=True
 def fail(self,error):
  if self.session.fault is None:self.session.fault=error
  self.ledger.poisoned=True
  self.failure={'error':type(error).__name__,'reason':str(error)[:600],'owned':getattr(error,'owned_receipt',None),'cleanup_confirmed':getattr(error,'cleanup_confirmed',False) is True}
 def finish(self):
  # After any optional failure this path is pure-file only; no native exporter.
  io.DEADLINE=min(self.clock()+60,self.ledger.phase_end('validation'))
  require(self.clock()<io.DEADLINE,'No final pure retention window')
  source.protected();source.tools_manifest()
  budget_record={'start':self.ledger.start,'epoch':self.ledger.epoch,'hard_deadline':self.ledger.hard_deadline,'events':self.ledger.events,'minutes':35,'poisoned':self.ledger.poisoned}
  qualified_titles=(['01-original-home'] if self.home else [])+(['03-original-photo-sampled','04-original-saved-library'] if self.photo else [])
  qualified_images={key:self.images[key] for key in qualified_titles}
  qualified_exports={item['attachment']['exportedFileName']:item['path'] for item in qualified_images.values()}
  result={**self.expected,'lane':self.lane,'product_sha':contract.PRODUCT,'source':self.source,'host':self.host,'device':self.device,'derived':str(self.derived),'results':self.results,'images':qualified_images,'exported_to_kept':qualified_exports,'home_capture_complete':self.home,'photo_history_complete':self.photo,'failure':self.failure,'device_cleanup_confirmed':self.cleaned,'complete':self.home and self.photo and self.cleaned and self.failure is None,'human_visual_review':'pending','durability':'runner-local verified copy; external retention requires actual upload success'}
  final_records={'commands.json':io.encoded(self.records),'job-budget.json':io.encoded(budget_record),'capture-result.json':io.encoded(result)}
  require(all(len(raw)<=evidence.FINAL_CAPS[name] for name,raw in final_records.items()),'Final metadata exceeds its reserved file cap')
  require(sum(map(len,final_records.values()))+evidence.FINAL_CAPS['files.json']<=evidence.FINAL_RESERVE,'Final metadata reserve insufficient')
  for name,raw in final_records.items():evidence.put(name,raw,final=True)
  rows,total=evidence.inventory(evidence.UPLOAD);evidence.put('files.json',io.encoded(rows),final=True)
  return evidence.verify_upload(evidence.UPLOAD,self.lane,self.expected,deadline=io.DEADLINE)

def main():
 p=argparse.ArgumentParser();p.add_argument('lane',choices=tuple(contract.ROWS));args=p.parse_args();value=None
 c=Controller(args.lane)
 try:c.execute()
 except BaseException as error:c.fail(error)
 try:value=c.finish()
 except BaseException as error:
  print(json.dumps({'incomplete':True,'primary_failure':c.failure,'evidence_error':type(error).__name__,'reason':str(error)[:300]}),flush=True)
  return 1
 print(json.dumps(value,sort_keys=True),flush=True)
 if os.environ.get('GITHUB_OUTPUT'):
  with open(os.environ['GITHUB_OUTPUT'],'a') as stream:stream.write('complete='+str(value['complete']).lower()+'\nhome_complete='+str(value['home_capture_complete']).lower()+'\n')
 return 0 if value['complete'] else 1
if __name__=='__main__':raise SystemExit(main())
