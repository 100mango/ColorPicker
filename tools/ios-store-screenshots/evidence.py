"""Original capture bytes and exact copied-package revalidation; no subprocesses."""
import hashlib,json,math,re,time
from pathlib import Path
import io_boundary as io
import capture_contract as contract

LIMIT=12*1024*1024
FINAL_RESERVE=196608
FINAL_CAPS={'commands.json':65536,'job-budget.json':32768,'capture-result.json':65536,'files.json':16384}
UPLOAD=io.REPO/'build/store-upload'

def require(value,message):
 if not value:raise ValueError(message)
def inventory(root):
 rows=[];total=0
 for p in root.iterdir():
  require(len(rows)<40 and p.is_file() and not p.is_symlink(),'Unsafe/non-flat upload inventory')
  raw=io.read(p,LIMIT);total+=len(raw);require(total<=LIMIT,'Actual upload exceeds12MiB')
  rows.append({'path':p.name,'bytes':len(raw),'sha256':io.digest(raw)})
 rows.sort(key=lambda row:row['path'])
 return rows,total

def put(name,raw,*,final=False):
 require(Path(name).name==name,'Unsafe upload basename')
 io.mkdir(UPLOAD);rows,total=inventory(UPLOAD)
 if final:require(name in FINAL_CAPS and len(raw)<=FINAL_CAPS[name],'Final metadata exceeds exact reserved cap')
 require(total+len(raw)<=LIMIT-(0 if final else FINAL_RESERVE),'Cannot preserve remaining required metadata within12MiB')
 io.write(UPLOAD/name,raw,maximum=LIMIT)

def images_from_manifest(manifest,role,summary,device,lane,read_image,deadline):
 method=contract.METHODS['home' if role=='home' else 'photo-history'].rsplit('/',1)[1]
 require(isinstance(manifest,list) and len(manifest)==1,'Expected exactly one selected-method export group')
 group=manifest[0];identifier='TouchColorOriginalDesignUITests/'+method
 require(group.get('testIdentifier') in (identifier,identifier+'()'),'Foreign attachment method')
 require(group.get('testIdentifierURL')=='test://com.apple.xcode/TouchColor/TouchColorUITests/'+identifier,'Foreign attachment method URL')
 rows=group.get('attachments');require(isinstance(rows,list) and len(rows)<=100,'Unbounded attachment inventory')
 selected={}
 for name in (['01-original-home'] if role=='home' else ['03-original-photo-sampled','04-original-saved-library']):
  pattern=re.compile(re.escape(name)+r'_[0-9]{1,10}_[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\.png')
  found=[r for r in rows if isinstance(r,dict) and pattern.fullmatch(r.get('suggestedHumanReadableName',''))]
  require(len(found)==1,'Missing/duplicate original PNG '+name);row=found[0];file=row.get('exportedFileName','')
  require(Path(file).name==file and re.fullmatch(r'[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\.png',file),'Unsafe original attachment filename')
  require(row.get('isAssociatedWithFailure') is False and row.get('deviceId')==device['uuid'] and row.get('deviceName')==device['owned_name'] and row.get('configurationName')=='Test Scheme Action','Foreign/failing attachment destination/configuration')
  stamp=row.get('timestamp');require(type(stamp) in (float,int) and math.isfinite(stamp) and summary['startTime']<=stamp<=summary['finishTime'],'Foreign attachment timestamp')
  raw=read_image(file);proof=contract.png_complete(raw,lane,deadline=deadline)
  projected={key:row[key] for key in ('exportedFileName','suggestedHumanReadableName','isAssociatedWithFailure','deviceId','deviceName','configurationName','timestamp')}
  require(len(io.encoded(projected))<=2048,'Projected image identity exceeds bounded proof size')
  selected[name]={'raw':raw,'proof':proof,'attachment':projected,'group':{k:group[k] for k in ('testIdentifier','testIdentifierURL')}}
 return selected

def verify_role(root,role,result,deadline):
 record=io.json_read(root/(role+'-command.json'),65536);summary=io.json_read(root/(role+'-summary.json'),256000)
 require(record['source_sha']==result['source_sha'] and record['run_id']==result['run_id'] and record['run_attempt']==result['run_attempt'] and record['job']==result['job'],'Role command source/run differs')
 require(record['owned']['owned_group_cleanup_confirmed'] is True and record['owned']['state']=='REAPED' and record['owned']['reap_calls']==1,'Role command cleanup incomplete')
 require(record['finished_monotonic']<=record['work_deadline']<=record['cleanup_deadline'],'Role exceeded original allocation')
 import commands
 require(record['argv']==commands.test(role,result['device']['uuid'],Path(result['derived']),Path(result['results'][role])),'Role argv/result differs')
 contract.bind_summary(summary,record,result['device'],result['lane'])
 log=io.read(root/(role+'.log'),2000000);contract.bind_cases(log,role)
 require(record['log']['bytes']==len(log) and record['log']['sha256']==io.digest(log),'Raw case stream differs')
 manifest=io.json_read(root/(role+'-attachments.json'),1048576)
 selected=images_from_manifest(manifest,role,summary,result['device'],result['lane'],lambda name:io.read(root/result['exported_to_kept'][name],2*1024*1024),deadline)
 for name,value in selected.items():
  declared=result['images'][name];require(declared['proof']==value['proof'] and declared['attachment']==value['attachment'] and declared['group']==value['group'],'Image result metadata differs')
 return sorted(selected)

def verify_upload(root,lane,expected,*,deadline):
 previous=io.DEADLINE;io.DEADLINE=min(deadline,previous if previous is not None else deadline)
 try:
  rows,total=inventory(root);result=io.json_read(root/'capture-result.json',65536)
  require(all(result.get(k)==v for k,v in expected.items()) and result.get('lane')==lane and result.get('product_sha')==contract.PRODUCT,'Upload source/run/lane differs')
  require(all(type(result.get(k)) is bool for k in ('complete','home_capture_complete','photo_history_complete','device_cleanup_confirmed')),'Invalid capture state flags')
  require(not result['complete'] or (result['home_capture_complete'] and result['photo_history_complete'] and result['device_cleanup_confirmed'] and result.get('failure') is None),'Contradictory complete capture state')
  manifest=io.json_read(root/'files.json',65536);actual={r['path']:r for r in rows if r['path']!='files.json'}
  require(isinstance(manifest,list) and len(manifest)==len(actual) and {r['path']:r for r in manifest}==actual,'Upload manifest byte closure differs')
  titles=(['01-original-home'] if result['home_capture_complete'] else [])+(['03-original-photo-sampled','04-original-saved-library'] if result['photo_history_complete'] else [])
  require(isinstance(result['images'],dict) and set(result['images'])==set(titles),'Declared role image set differs')
  exact_mapping={}
  for title in titles:
   item=result['images'][title];name=title+'.png'
   require(item['path']==name and name in actual,'Required image path is not its retained flat basename')
   exported=item['attachment']['exportedFileName'];require(exported not in exact_mapping,'Duplicate exported image identity')
   exact_mapping[exported]=name
  require(result['exported_to_kept']==exact_mapping,'Export mapping escapes or differs from retained image paths')
  if result.get('home_capture_complete') is True:
   for required in ('source.json','host.json','device.json','self-test.json','commands.json','job-budget.json','runtime-devices.json','bootstatus.json','bootstatus.log','fixture.json','six-colors.png','source.log','host.log','xcode.log'):
    require(required in actual,'Missing provenance '+required)
   source=io.json_read(root/'source.json',65536);host=io.json_read(root/'host.json',65536);device=io.json_read(root/'device.json',65536)
   require(source==result['source'] and source['sha']==result['source_sha'] and source['parent']==contract.PRODUCT,'Source proof differs')
   require(host==result['host'] and (host['version'],host['build']) in {('27.0','26A428'),('27.0.1','26A434')} and host['xcode']==['Xcode 27.0','Build version 27A266a'],'Actual toolchain differs')
   require(device==result['device'] and device['mapping']['device_type']==contract.ROWS[lane]['type'] and device['mapping']['runtime']==contract.RUNTIME and device['mapping']['runtime_build']==contract.RUNTIME_BUILD,'Actual device mapping differs')
   metadata=io.json_read(root/'runtime-devices.json',1048576)
   require(contract.choose_device(metadata['runtimes'],metadata['devicetypes'],lane)==device['mapping'],'Fresh supported-device metadata differs')
   require(device['uuid'] not in contract.existing_device_ids(metadata),'Capture UUID already existed before create')
   records=io.json_read(root/'commands.json',262144);budget=io.json_read(root/'job-budget.json',65536)
   require(budget.get('minutes')==35,'Wrong capture budget')
   required_commands=['source','clean-start','host','xcode','runtime-devices','build','create','boot','ready','home','home-summary','home-export']
   if result['photo_history_complete']:required_commands+=['seed','photo','photo-summary','photo-export']
   if result['device_cleanup_confirmed']:required_commands+=['device-shutdown','device-delete']
   import commands
   exact_argv=commands.expected_native(result)
   for key in required_commands:
    record=records[key]
    require(all(record.get(k)==v for k,v in expected.items()) and record['exit']==0 and record['argv']==exact_argv[key],'Command source/run/exit/argv differs')
    require(record['owned']['state']=='REAPED' and record['owned']['reap_calls']==1 and record['owned']['owned_group_cleanup_confirmed'] is True,'Command cleanup differs')
    require(record['finished_monotonic']<=record['work_deadline']<record['cleanup_deadline']<=budget['hard_deadline'],'Command allocation differs')
   for key,name,cap in [('source','source.log',65536),('host','host.log',65536),('xcode','xcode.log',65536),('runtime-devices','runtime-devices.json',1048576),('home-summary','home-summary.json',256000)]+([('photo-summary','photo-summary.json',256000)] if result['photo_history_complete'] else []):
    raw=io.read(root/name,cap);require(records[key]['log']=={'bytes':len(raw),'sha256':io.digest(raw)},'Original command stdout binding differs: '+key)
   require(io.read(root/'source.log',65536).decode().strip().splitlines()==[source['sha'],source['tree'],contract.PRODUCT],'Actual source log differs')
   actual_host=dict(re.findall(r'^(ProductName|ProductVersion|BuildVersion):\s*(.*?)\s*$',io.read(root/'host.log',65536).decode(),re.M))
   require(actual_host.get('ProductVersion')==host['version'] and actual_host.get('BuildVersion')==host['build'] and io.read(root/'xcode.log',65536).decode().strip().splitlines()==host['xcode'],'Actual host/toolchain log differs')
   require(records['clean-start']['log']=={'bytes':0,'sha256':io.digest(b'')},'Clean-source stdout differs')
   require(records['home']==io.json_read(root/'home-command.json',65536),'Home copied command differs')
   if result['photo_history_complete']:require(records['photo']==io.json_read(root/'photo-command.json',65536),'Photo copied command differs')
   import commands
   require(records['build']['argv']==commands.build(Path(result['derived'])),'Built scheme/product command differs')
   prerequisite=io.json_read(root/'self-test.json',65536)
   child=prerequisite['child'];owned=prerequisite['owned']
   require(prerequisite['scope']=='fixed_launcher_prerequisite_only' and prerequisite['complete'] is True and prerequisite['product_qualified'] is False,'Launcher scope differs')
   require(set(child)=={'pid','pgid','sid','fds','mask'} and all(type(child[k]) is int and child[k]>0 for k in ('pid','pgid','sid')) and child['pid']==child['pgid']==child['sid']==owned['pid'],'Launcher identity differs')
   require(child['fds']==[0,1,2] and all(type(v) is int for v in child['fds']) and child['mask']==[] and owned['state']=='REAPED' and type(owned['reap_calls']) is int and owned['reap_calls']==1 and type(owned['lease_calls']) is int and owned['lease_calls']>=2 and type(owned['group_calls']) is int and owned['group_calls']>=1 and owned['owned_group_cleanup_confirmed'] is True,'Launcher prerequisite missing')
   boot=io.json_read(root/'bootstatus.json',65536);raw=io.read(root/'bootstatus.log',65536)
   require(boot.get('stdout_sha256')==io.digest(raw) and boot.get('stdout_bytes')==len(raw) and records['ready']['log']=={'sha256':io.digest(raw),'bytes':len(raw)},'Boot proof stream differs')
   import source_helpers
   require(boot==source_helpers.bootstatus(raw.decode(),{'name':device['owned_name'],'device':device['uuid']}),'Boot completion differs from exact parser')
   fixture=io.json_read(root/'fixture.json',65536);raw=io.read(root/'six-colors.png',65536)
   require(fixture=={'bytes':1675,'sha256':'6190ef70ec7da8b038c026cb8ffc0fc03b40a67ebdc6a382ee68b502135874ba','source':'exact922 original_design_gate.fixture_png'} and len(raw)==fixture['bytes'] and io.digest(raw)==fixture['sha256'],'Exact frozen fixture differs')
   verify_role(root,'home',result,deadline)
   if result.get('photo_history_complete') is True:verify_role(root,'photo',result,deadline)
  # Rescan after all parsing; a size/hash snapshot cannot excuse late mutation.
  again,size=inventory(root);require(again==rows and size==total,'Upload changed during verification')
  return result
 finally:io.DEADLINE=previous
