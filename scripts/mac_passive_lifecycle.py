"""Bounded, app/PID/token-scoped Mac lifecycle observation; never UI acceptance."""
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time

from palette_lifecycle_diagnostics import capture, CaptureStopped, valid_uuid
from retain_mac_evidence import read_file, strict_json, workflow_identity

PREFIX = 'MAC_PASSIVE_LIFECYCLE '
ATTACHMENT = 'Native Mac accessibility issue lifecycle identity '
OUTPUT = 'mac-passive-lifecycle.json'
RAW_LIMIT = 512 * 1024
OUTPUT_LIMIT = 128 * 1024
SECONDS = 30
CONTRACT = 'fixed-app-scoped-log-show-v1'
CASES = ('testExplicitPrivacyContactHasEnglishLinkSemanticsWithoutOpeningMail',
         'testExplicitPrivacyContactHasSimplifiedChineseLinkSemanticsWithoutOpeningMail',
         'testNativeFileSamplingZoomPalettePersistenceAndPrivacy',
         'testSimplifiedChineseNativeSamplingFlowAndScreenshot')
EVENTS = {'appInit','willFinishLaunching','didFinishRestoringWindows','didFinishLaunching',
          'didBecomeActive','didResignActive','didHide','didUnhide','windowKey','windowResignKey',
          'windowMiniaturized','windowDeminiaturized','windowOcclusion','windowWillClose',
          'markerCreated','markerMapped','markerDetached','census','final'}
SCENE_CHECKPOINTS = {'sceneBody','windowContentEntered','windowContentReturned','colorWindowBody'}
EVENTS |= SCENE_CHECKPOINTS

def require(value, reason):
    if not value: raise ValueError(reason)

def number(value): return type(value) in (int,float) and math.isfinite(value)
def integer(value, low=0, high=2**31-1): return type(value) is int and low <= value <= high
def digest(raw): return hashlib.sha256(raw).hexdigest()
def encode(value): return (json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':'))+'\n').encode()

def launch_args(case, ordinal):
    if case == CASES[0]: return ['--ui-test-reset','-AppleLanguages','(en)','-AppleLocale','en_US']
    if case == CASES[1] or (case == CASES[3] and ordinal == 2):
        return ['--ui-test-reset','-AppleLanguages','(zh-Hans)','-AppleLocale','zh_CN']
    return ['--ui-test-reset']

def identity_scope(group, item):
    name=item.get('suggestedHumanReadableName','')
    if not isinstance(name,str) or len(name)>512:return None
    match=re.fullmatch(re.escape(ATTACHMENT)+r'([0-9A-F-]{36}) ([12])_.+',name)
    if match is None or not valid_uuid(match[1]):return None
    case=next((case for case in CASES if group.get('testIdentifier')=='TouchColorMacUITests/'+case+'()'),None)
    if case is None or group.get('testIdentifierURL')!='test://com.apple.xcode/TouchColorMac/TouchColorMacUITests/TouchColorMacUITests/'+case:return None
    ordinal=int(match[2])
    if ordinal==2 and case!=CASES[3]:return None
    return {'case':case,'token':match[1],'ordinal':ordinal}


def identities(root, only_files=None):
    """Read only existing source-bound xcresult exports, at most ten processes."""
    rows=[];keys=set();tokens={};products={}
    for folder,lane,summary_name in [('screenshots',False,'mac-ui-summary.json'),
                                     ('sandbox-screenshots',True,'mac-sandbox-summary.json')]:
        path=root/folder/'manifest.json'
        if not path.exists(): continue
        require(not path.parent.is_symlink(),'linked export directory')
        summary=strict_json(read_file(root/summary_name,1_000_000))
        start,end=summary.get('startTime'),summary.get('finishTime')
        require(number(start) and number(end) and start<end,'missing result interval')
        configurations=summary.get('devicesAndConfigurations')
        require(isinstance(configurations,list) and len(configurations)==1,'ambiguous result destination')
        configuration=configurations[0];device=configuration.get('device',{})
        require(all(device.get(k)==v for k,v in {'platform':'macOS','architecture':'arm64','osVersion':'27.0'}.items())
                and isinstance(device.get('deviceId'),str) and device['deviceId'],'wrong Mac destination')
        require(configuration.get('testPlanConfiguration',{}).get('configurationName')=='Test Scheme Action','wrong configuration')
        groups=strict_json(read_file(path,1_000_000));require(isinstance(groups,list) and len(groups)<=64,'export group limit')
        for group in groups:
            require(isinstance(group,dict) and isinstance(group.get('attachments'),list) and len(group['attachments'])<=512,'bad export group')
            for item in group['attachments']:
                name=item.get('suggestedHumanReadableName','')
                if not name.startswith(ATTACHMENT):continue
                filename=item.get('exportedFileName','');require(re.fullmatch(r'[0-9A-Fa-f-]{36}\.txt',filename),'bad receipt path')
                if only_files is not None and folder+'/'+filename not in only_files:continue
                raw=read_file(path.parent/filename,4096);row=strict_json(raw)
                fields={'v','token','pid','test','ordinal','started','captured','args','sandbox','bundle','applicationPath',
                        'expectedPath','executable','executableSHA256','logicSHA256','xctestPID','xctestPIDReason'}
                require(isinstance(row,dict) and set(row)==fields and type(row['v']) is int and row['v']==1,'bad receipt fields')
                case=next((x for x in CASES if row['test']=='-[TouchColorMacUITests '+x+']'),None)
                require(case is not None and group.get('testIdentifier')=='TouchColorMacUITests/'+case+'()','foreign test receipt')
                require(group.get('testIdentifierURL')=='test://com.apple.xcode/TouchColorMac/TouchColorMacUITests/TouchColorMacUITests/'+case,'foreign test URL')
                require(valid_uuid(row['token']) and integer(row['pid'],1) and integer(row['ordinal'],1,2),'invalid process correlation')
                require(row['ordinal']==1 or case==CASES[3],'unexpected relaunch')
                require(identity_scope(group,item)=={'case':case,'token':row['token'],'ordinal':row['ordinal']},'uncorrelated identity title')
                require(row['args']==launch_args(case,row['ordinal']) and row['sandbox'] is lane,'wrong lane or arguments')
                require(number(row['started']) and number(row['captured']) and start<=row['started']<=row['captured']<=end,'stale receipt')
                require(number(item.get('timestamp')) and row['captured']<=item['timestamp']+.001 and item['timestamp']<=end+.001,'unbound receipt attachment')
                require(item.get('deviceId')==device['deviceId'] and item.get('configurationName')=='Test Scheme Action','foreign attachment destination')
                require(row['bundle']=='com.mango.touchColor' and row['applicationPath']==row['expectedPath'],'wrong product')
                app=row['applicationPath'];require(isinstance(app,str) and len(app)<=768 and app.startswith('/') and app.endswith('/Build/Products/Debug/TouchColor.app') and '..' not in Path(app).parts,'bad product path')
                require(('/mac-sandbox/' in app)==lane and row['executable']==app+'/Contents/MacOS/TouchColor','wrong executable/lane')
                require(all(re.fullmatch('[0-9a-f]{64}',row[x]) for x in ('executableSHA256','logicSHA256')),'missing product hashes')
                require(row['xctestPID'] is None and row['xctestPIDReason']=='No public PID query; correlate retained failure hierarchy independently','invented XCTest PID')
                key=(row['token'],row['ordinal']);require(key not in keys and len(rows)<10,'duplicate or excessive process')
                keys.add(key)
                prior=tokens.setdefault(row['token'],(case,lane));require(prior==(case,lane),'cross-test token')
                product=(app,row['executableSHA256'],row['logicSHA256']);require(products.setdefault(lane,product)==product,'product changed within lane')
                row.update(case=case,result_start=start,result_end=end,receipt_sha256=digest(raw),receipt_file=folder+'/'+filename)
                rows.append(row)
    require(len({(r['pid'],r['token']) for r in rows})==len(rows),'reused process correlation')
    return rows

def command(rows):
    require(rows and len(rows)<=10,'no process query')
    start=min(x['started'] for x in rows);end=max(x['result_end'] for x in rows)
    date=lambda value:datetime.datetime.fromtimestamp(value,datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S%z')
    terms=['(processID == %d AND eventMessage CONTAINS "%s")'%(x['pid'],x['token']) for x in rows]
    predicate='process == "TouchColor" AND eventMessage BEGINSWITH "'+PREFIX+'" AND ('+' OR '.join(terms)+')'
    return ['/usr/bin/log','show','--style','json','--start',date(math.floor(start)),
            '--end',date(math.ceil(end)),'--predicate',predicate]

def validate_census(app):
    require(isinstance(app,dict) and type(app.get('present')) is bool,'missing app state')
    if app['present'] is False:
        require(set(app)=={'present'},'absent app has invented fields');return
    require(set(app)=={'present','running','active','hidden','policy','count','omitted','key','main','windows'},'unknown app fields')
    require(all(type(app[k]) is bool for k in ('running','active','hidden')) and integer(app['policy'],0,2),'bad app state')
    require(integer(app['count']) and app['omitted']==max(0,app['count']-4) and type(app['omitted']) is int,'window omission mismatch')
    require(all(app[k] is None or integer(app[k],1,16) for k in ('key','main')),'bad window reference')
    require(isinstance(app['windows'],list) and len(app['windows'])==min(4,app['count']),'bad window inventory')
    seen=set()
    for window in app['windows']:
        require(isinstance(window,dict) and set(window)=={'id','number','frame','visible','miniaturized','key','main','occlusion','restorable','restorationClass','autosaveName','sheet','workspace'},'unknown window fields')
        require(window['id'] is None or integer(window['id'],1,16),'bad window identity')
        if window['id'] is not None:
            require(window['id'] not in seen,'duplicate window identity');seen.add(window['id'])
        require(integer(window['number'],-1) and integer(window['occlusion']),'bad window scalar')
        require(isinstance(window['frame'],list) and len(window['frame'])==4 and all(number(v) and abs(v)<10**7 for v in window['frame']) and all(v>=0 for v in window['frame'][2:]),'bad window frame')
        require(all(type(window[k]) is bool for k in ('visible','miniaturized','key','main','restorable','restorationClass','autosaveName','sheet','workspace')),'bad window boolean')

def project(raw, receipts):
    records=strict_json(raw);require(isinstance(records,list) and len(records)<=240,'too many log rows')
    by_key={(r['pid'],r['token']):r for r in receipts};buckets={key:[] for key in by_key};seen=set();launches={};sizes={};checkpoints=set()
    for record in records:
        require(isinstance(record,dict) and type(record.get('processID')) is int,'bad log envelope')
        message=record.get('eventMessage');require(isinstance(message,str) and message.startswith(PREFIX),'redacted or foreign message')
        value=strict_json(message[len(PREFIX):]);require(isinstance(value,dict),'bad embedded object')
        common={'v','token','launch','pid','epoch','elapsed','sequence','event','omittedRecords','late'}
        require(common<=set(value)<=common|{'app','product','launchIsDefault'},'unapproved record fields')
        require(type(value['v']) is int and value['v']==1 and integer(value['pid'],1) and valid_uuid(value['token']) and valid_uuid(value['launch']),'bad record identity')
        key=(value['pid'],value['token']);require(key in by_key,'foreign PID/token');receipt=by_key[key]
        require(record['processID']==value['pid'] and record.get('processImagePath')==receipt['executable'],'foreign process image')
        require(value['event'] in EVENTS and integer(value['sequence'],1,24) and integer(value['omittedRecords']) and type(value['late']) is bool,'bad event fields')
        if value['event'] in SCENE_CHECKPOINTS:
            checkpoint=(key,value['event'])
            require(checkpoint not in checkpoints,'duplicate scene checkpoint');checkpoints.add(checkpoint)
        if 'launchIsDefault' in value:
            require(value['event']=='didFinishLaunching' and type(value['launchIsDefault']) is str
                    and value['launchIsDefault'] in {'missing','reportedTrue','reportedFalse','unexpectedType'},'invalid default-launch scalar')
        require(number(value['epoch']) and receipt['started']<=value['epoch']<=receipt['result_end'] and number(value['elapsed']) and value['elapsed']>=0,'out-of-window event')
        require(value['late']==(value['elapsed']>10) and (not value['late'] or value['event']=='final'),'late event is not a final omission')
        require(('app' in value)==(not value['late'] and value['event'] not in SCENE_CHECKPOINTS),'missing or invented census')
        if 'app' in value:validate_census(value['app'])
        if value['event']=='appInit':
            require(value['sequence']==1 and 'product' in value,'missing header')
            product=value['product'];require(isinstance(product,dict) and all(type(product.get(k)) is bool for k in ('reset','suitePresent','modalPresent','sandboxProbePresent')),'bad product booleans');args=receipt['args'];language=args[2] if len(args)>1 else None;locale=args[4] if len(args)>1 else None
            require(product=={'bundle':'com.mango.touchColor','path':receipt['applicationPath'],'executable':receipt['executable'],
                              'reset':True,'language':language,'locale':locale,'suitePresent':True,'modalPresent':False,'sandboxProbePresent':False},'product/argument mismatch')
        else:require('product' not in value,'unexpected header')
        seq=(key,value['sequence']);require(seq not in seen,'duplicate event');seen.add(seq)
        require(launches.setdefault(key,value['launch'])==value['launch'],'ambiguous process launch')
        sizes[key]=sizes.get(key,0)+len(message.encode());require(sizes[key]<=12288 and len(message.encode())<=4096,'producer byte ceiling exceeded')
        buckets[key].append(value)
    result=[]
    for key,receipt in by_key.items():
        events=sorted(buckets[key],key=lambda r:r['sequence'])
        require(all(a['epoch']<=b['epoch'] and a['elapsed']<=b['elapsed'] for a,b in zip(events,events[1:])),'nonmonotonic lifecycle')
        result.append({'identity':receipt,'events':events,'app_header_observed':any(e['event']=='appInit' for e in events),
                       'final_observed':any(e['event']=='final' for e in events),'sequence_gaps':([i for i in range(1,events[-1]['sequence']+1) if i not in {e['sequence'] for e in events}] if events else []),
                       'status':'records-retained' if events else 'observation-gap','absence_is_not_proof':True})
    require(len(encode(result))<=OUTPUT_LIMIT-4096,'projected evidence too large');return result

def stderr_classification(raw):
    """Only verified diagnostic prefixes indicate failure; other stderr is evidence, not readiness."""
    text=raw.decode('utf-8',errors='replace')
    if re.search(r'^(?:log:\s*)?(?:permission denied|operation not permitted|access denied)\b',text,re.I|re.M):
        return 'permission-denied'
    if re.search(r'^(?:log:\s*)?(?:error:|failed to\b|unable to\b|unknown (?:option|command)\b|unrecognized option\b|invalid option\b)',text,re.I|re.M):
        return 'verified-error'
    return 'empty' if not raw else 'unclassified'


def validate_commands(value):
    commands=value['commands']
    require(isinstance(commands,list) and len(commands)<=3,'unbounded command facts')
    stages=('source-head','source-clean','query')
    known=0
    for index,row in enumerate(commands):
        require(isinstance(row,dict) and set(row)=={'stage','returned','exit','cleanup_confirmed','stdout_bytes','stderr_bytes','stderr_classification','elapsed_seconds','timely'},'unknown command fields')
        require(row['stage']==stages[index] and type(row['returned']) is bool,'unplanned command stage')
        require(row['exit'] is None or integer(row['exit'],-255,255),'invalid command exit')
        require(row['cleanup_confirmed'] is None or type(row['cleanup_confirmed']) is bool,'invalid owned cleanup')
        require(number(row['elapsed_seconds']) and row['elapsed_seconds']>=0 and type(row['timely']) is bool,'invalid command timing')
        require(row['stderr_classification'] in ('unobserved','empty','unclassified','permission-denied','verified-error'),'invalid stderr classification')
        if row['returned']:
            require(integer(row['stdout_bytes'],0,RAW_LIMIT) and integer(row['stderr_bytes'],0,RAW_LIMIT)
                    and row['exit'] is not None and row['cleanup_confirmed'] is True,'incomplete returned command')
            require(row['stderr_classification']!='unobserved'
                    and (row['stderr_classification']=='empty')==(row['stderr_bytes']==0),'inconsistent stderr facts')
            known+=row['stdout_bytes']+row['stderr_bytes']
        else:
            require(row['exit'] is None and row['stdout_bytes'] is None and row['stderr_bytes'] is None
                    and row['stderr_classification']=='unobserved','invented interrupted output')
        successful=row['returned'] and row['exit']==0 and row['cleanup_confirmed'] is True and row['timely']
        if index<len(commands)-1:require(successful,'continued after command uncertainty/failure')
    require(known==value['raw_bytes'],'command byte accounting mismatch')
    require(value['host_cleanup_confirmed']==(commands[-1]['cleanup_confirmed'] if commands else None),'aggregate cleanup contradiction')
    if value['status']=='observation-only':
        require(value['reason']=='missing-records-and-restoration-notifications-are-not-proof-of-window-cause','observation reason contradiction')
        require(len(commands)==3 and all(row['returned'] and row['exit']==0 and row['cleanup_confirmed'] is True and row['timely'] for row in commands),'observation without completed fixed command sequence')
        require(commands[-1]['stderr_classification'] in ('empty','unclassified'),'observation after verified query error')


def validate_projection(raw, source):
    """Closed observation schema tied to the already verified Mac retention source."""
    value=strict_json(raw)
    required={'schema','status','acceptance','source','records','host_cleanup_confirmed','raw_bytes','omissions','budget_seconds','elapsed_seconds','reason','contract','commands'}
    require(isinstance(value,dict) and required<=set(value)<=required|{'detail','missing_process_receipts'},'unknown projection schema')
    require(type(value['schema']) is int and value['schema']==2 and value['contract']==CONTRACT and value['acceptance'] is False and value['budget_seconds']==30
            and type(value['budget_seconds']) is int and value['status'] in ('unavailable','observation-only'),'invalid projection status')
    binding={key:source[key] for key in ('repository','ref','workflow_ref','workflow_file','event_name','sha','run_id')}
    binding['attempt']=source['run_attempt']
    require(value['source']==binding,'projection belongs to another source/run/workflow')
    require(integer(value['raw_bytes'],0,RAW_LIMIT) and number(value['elapsed_seconds']) and value['elapsed_seconds']>=0
            and (value['host_cleanup_confirmed'] is None or type(value['host_cleanup_confirmed']) is bool)
            and value['omissions']==[],'invalid projection bounds')
    validate_commands(value)
    reasons={'no-current-process-receipts','log-query-failed','log-query-permission-denied','log-query-verified-error',
             'missing-records-and-restoration-notifications-are-not-proof-of-window-cause',
             'owned-capture-stopped','invalid-or-unavailable-evidence'}
    require(value['reason'] in reasons,'unknown projection reason')
    if 'detail' in value:require(isinstance(value['detail'],str) and re.fullmatch('[A-Za-z]{1,48}',value['detail']),'invalid diagnostic type')
    missing=value.get('missing_process_receipts',[]);require(isinstance(missing,list) and len(missing)<=10,'unbounded missing receipt list')
    seen=set()
    for row in missing:
        require(isinstance(row,dict) and set(row)=={'case','sandbox','ordinal','reason'} and row['case'] in CASES
                and type(row['sandbox']) is bool and integer(row['ordinal'],1,2)
                and (row['ordinal']==1 or row['case']==CASES[3])
                and row['reason']=='Identity unavailable; execution or collection may be incomplete','invalid missing receipt')
        key=(row['case'],row['sandbox'],row['ordinal']);require(key not in seen,'duplicate missing receipt');seen.add(key)
    records=value['records'];require(isinstance(records,list) and len(records)<=10,'unbounded projected processes')
    if value['status']=='unavailable':require(not records,'unavailable projection includes unverified records');return value
    require(value['host_cleanup_confirmed'] is True and value['elapsed_seconds']<30,'late/unconfirmed observation')
    identities_list=[];envelopes=[];keys=set()
    identity_fields={'v','token','pid','test','ordinal','started','captured','args','sandbox','bundle','applicationPath',
                     'expectedPath','executable','executableSHA256','logicSHA256','xctestPID','xctestPIDReason',
                     'case','result_start','result_end','receipt_sha256','receipt_file'}
    for row in records:
        require(isinstance(row,dict) and set(row)=={'identity','events','app_header_observed','final_observed','sequence_gaps','status','absence_is_not_proof'},'unknown projected process fields')
        require(type(row['app_header_observed']) is bool and type(row['final_observed']) is bool and row['absence_is_not_proof'] is True
                and isinstance(row['sequence_gaps'],list) and len(row['sequence_gaps'])<=24 and all(integer(v,1,24) for v in row['sequence_gaps']), 'invalid projected flags/gaps')
        identity=row['identity'];require(isinstance(identity,dict) and set(identity)==identity_fields,'unknown identity fields')
        require(type(identity['v']) is int and identity['v']==1 and identity['case'] in CASES and identity['test']=='-[TouchColorMacUITests '+identity['case']+']'
                and valid_uuid(identity['token']) and integer(identity['pid'],1) and integer(identity['ordinal'],1,2)
                and (identity['ordinal']==1 or identity['case']==CASES[3]) and type(identity['sandbox']) is bool
                and identity['args']==launch_args(identity['case'],identity['ordinal']),'invalid identity scope')
        key=(identity['pid'],identity['token']);require(key not in keys,'duplicate identity');keys.add(key)
        require(all(number(identity[k]) for k in ('result_start','started','captured','result_end'))
                and identity['result_start']<=identity['started']<=identity['captured']<=identity['result_end'],'invalid identity interval')
        app=identity['applicationPath'];require(isinstance(app,str) and len(app)<=768 and app.startswith('/')
                and app.endswith('/Build/Products/Debug/TouchColor.app') and '..' not in Path(app).parts
                and identity['expectedPath']==app and identity['executable']==app+'/Contents/MacOS/TouchColor'
                and identity['bundle']=='com.mango.touchColor' and ('/mac-sandbox/' in app)==identity['sandbox'],'invalid product identity')
        require(all(isinstance(identity[k],str) and re.fullmatch('[0-9a-f]{64}',identity[k]) for k in ('executableSHA256','logicSHA256','receipt_sha256')),'invalid identity hash')
        folder='sandbox-screenshots' if identity['sandbox'] else 'screenshots'
        require(isinstance(identity['receipt_file'],str) and re.fullmatch(re.escape(folder)+r'/[0-9A-Fa-f-]{36}\.txt',identity['receipt_file'])
                and identity['xctestPID'] is None and identity['xctestPIDReason']=='No public PID query; correlate retained failure hierarchy independently','invalid identity receipt path')
        require(isinstance(row['events'],list) and len(row['events'])<=24,'unbounded projected events')
        identities_list.append(identity)
        for event in row['events']:
            envelopes.append({'processID':identity['pid'],'processImagePath':identity['executable'],'eventMessage':PREFIX+json.dumps(event,separators=(',',':'),ensure_ascii=False)})
    require(project(encode(envelopes),identities_list)==records,'projected event facts do not reconstruct')
    return value

def collect(root, env=os.environ, runner=capture, clock=time.monotonic):
    started=clock();deadline=started+SECONDS;spent=0
    result={'schema':2,'contract':CONTRACT,'commands':[],'status':'unavailable','acceptance':False,'source':None,'records':[],
            'host_cleanup_confirmed':None,'raw_bytes':0,'omissions':[],'budget_seconds':SECONDS}
    def invoke(stage,argv,cap):
        nonlocal spent
        command_deadline=deadline-4
        require(clock()<command_deadline and spent<RAW_LIMIT,'collection deadline exhausted')
        began=clock();row={'stage':stage,'returned':False,'exit':None,'cleanup_confirmed':None,
            'stdout_bytes':None,'stderr_bytes':None,'stderr_classification':'unobserved','elapsed_seconds':0,'timely':False}
        result['commands'].append(row)
        result['host_cleanup_confirmed']=None
        try:
            remaining=command_deadline-clock()
            require(remaining>0,'collection deadline expired before capture')
            response=runner(argv,seconds=remaining,cap=min(cap,RAW_LIMIT-spent))
            row.update(returned=True,exit=response.returncode,cleanup_confirmed=True,
                stdout_bytes=len(response.stdout),stderr_bytes=len(response.stderr),
                stderr_classification=stderr_classification(response.stderr))
            result['host_cleanup_confirmed']=True
            spent+=len(response.stdout)+len(response.stderr)
            row['timely']=clock()<command_deadline
            require(row['timely'],'late collection command')
            require(spent<=RAW_LIMIT,'raw evidence ceiling exceeded')
            return response
        except CaptureStopped as error:
            row['cleanup_confirmed']=error.cleanup_confirmed
            raise
        finally:row['elapsed_seconds']=clock()-began
    try:
        identity=workflow_identity(env);require(identity['workflow_file']=='.github/workflows/mac-watch-repair.yml','dedicated Mac workflow required')
        sha=env.get('GITHUB_SHA','');require(re.fullmatch('[0-9a-f]{40}',sha) and env.get('GITHUB_WORKFLOW_SHA')==sha,'wrong source')
        require(env.get('TOUCHCOLOR_JOB_PLATFORM')=='mac' and env.get('TOUCHCOLOR_EVIDENCE_LIMIT')=='3000000','wrong lane/budget')
        require(all(re.fullmatch('[1-9][0-9]*',env.get(k,'')) for k in ('GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT')),'missing run binding')
        for stage,argv,expected in [('source-head',['git','rev-parse','HEAD'],sha),('source-clean',['git','status','--porcelain','--untracked-files=all'],'')]:
            response=invoke(stage,argv,8192);require(response.returncode==0 and response.stdout.decode().strip()==expected,'unclean source')
        result['source']={**identity,'sha':sha,'run_id':env['GITHUB_RUN_ID'],'attempt':env['GITHUB_RUN_ATTEMPT']}
        receipts=identities(root);require(clock()<deadline-4,'identity reading exceeded deadline')
        observed={(row['case'],row['sandbox'],row['ordinal']) for row in receipts}
        result['missing_process_receipts']=[{'case':case,'sandbox':lane,'ordinal':ordinal,
            'reason':'Identity unavailable; execution or collection may be incomplete'}
            for lane in (False,True) for case in CASES for ordinal in ((1,2) if case==CASES[3] else (1,))
            if (case,lane,ordinal) not in observed]
        if not receipts:result['reason']='no-current-process-receipts';return result
        # Fixed public compatibility attempt, not a help-layout inference.
        response=invoke('query',command(receipts),RAW_LIMIT-spent)
        diagnostic=result['commands'][-1]['stderr_classification']
        if diagnostic=='permission-denied':result['reason']='log-query-permission-denied';return result
        if diagnostic=='verified-error':result['reason']='log-query-verified-error';return result
        if response.returncode!=0:result['reason']='log-query-failed';return result
        projected=project(response.stdout,receipts);require(clock()<deadline,'projection exceeded deadline')
        result.update(status='observation-only',records=projected,host_cleanup_confirmed=True,
                      reason='missing-records-and-restoration-notifications-are-not-proof-of-window-cause')
    except CaptureStopped as error:
        result.update(reason='owned-capture-stopped',host_cleanup_confirmed=error.cleanup_confirmed)
        if error.cancelled_signal is not None:raise
    except (ValueError,OSError,UnicodeError,TypeError,KeyError) as error:
        result.update(reason='invalid-or-unavailable-evidence',detail=type(error).__name__)
    finally:result['raw_bytes']=spent;result['elapsed_seconds']=clock()-started
    require(len(encode(result))<=OUTPUT_LIMIT,'projection ceiling');return result

def main():
    if os.environ.get('TOUCHCOLOR_JOB_PLATFORM')!='mac':return
    root=Path('build/evidence');require(root.is_dir() and not root.is_symlink(),'unsafe evidence root')
    target=root/OUTPUT;require(not target.exists() and not target.is_symlink(),'do not overwrite prior observation')
    result=collect(root);raw=encode(result);require(len(raw)<=OUTPUT_LIMIT,'output cap')
    with target.open('xb') as output:output.write(raw)

if __name__=='__main__':main()
