"""Exact35-minute capture route; phase allocations include per-child cleanup."""
from capture_contract import METHODS

def step(name,seconds,cleanup=20,local=False):return {'id':name,'seconds':seconds,'cleanup':cleanup,'local':local}
def stages(lane):
 return [
  {'id':'setup','seconds':240,'commands':[step('self-test',25),step('source',25),step('clean-start',25),step('host',25),step('xcode',25),step('runtime-devices',25),step('setup-proof',10,0,True)]},
  {'id':'build','seconds':360,'commands':[step('build',359)]},
  {'id':'device','seconds':400,'commands':[step('create',40),step('boot',40),step('ready',319)]},
  {'id':'home','seconds':220,'commands':[step('home',219)]},
  {'id':'home-proof','seconds':100,'commands':[step('home-summary',40),step('home-export',40),step('home-proof',19,0,True)]},
  {'id':'seed','seconds':80,'commands':[step('seed',79)]},
  {'id':'photo','seconds':220,'commands':[step('photo',219)]},
  {'id':'photo-proof','seconds':100,'commands':[step('photo-summary',40),step('photo-export',40),step('photo-proof',19,0,True)]},
 ]
def build(derived):return ['/usr/bin/xcodebuild','-project','TouchColor.xcodeproj','-scheme','TouchColor','-configuration','Debug','-destination','generic/platform=iOS Simulator','-derivedDataPath',str(derived),'-jobs','2','-only-testing:TouchColorUITests','CODE_SIGNING_ALLOWED=NO','build-for-testing']
def test(role,device,derived,result):
 return ['/usr/bin/xcodebuild','-project','TouchColor.xcodeproj','-scheme','TouchColor','-configuration','Debug','-destination','platform=iOS Simulator,id='+device,'-derivedDataPath',str(derived),'-resultBundlePath',str(result),'-parallel-testing-enabled','NO','-collect-test-diagnostics','never','-test-timeouts-enabled','YES','-default-test-execution-time-allowance','120','-maximum-test-execution-time-allowance','180','-only-testing:'+METHODS['home' if role=='home' else 'photo-history'],'CODE_SIGNING_ALLOWED=NO','test-without-building']


def expected_native(result):
 from pathlib import Path
 import io_boundary as io
 work=io.REPO/'build/store-capture';device=result['device'];identity=device['uuid']
 derived=work/'derived';mapping=device['mapping']
 name='TouchColor Store '+result['lane']+' '+result['source_sha']+' '+result['run_id']+'-'+result['run_attempt']
 if result['derived']!=str(derived) or device['owned_name']!=name:raise ValueError('Foreign owned capture paths/name')
 values={'source':['/usr/bin/git','show','-s','--format=%H%n%T%n%P','HEAD'],
  'clean-start':['/usr/bin/git','status','--porcelain','--untracked-files=all'],
  'host':['/usr/bin/sw_vers'],'xcode':['/usr/bin/xcodebuild','-version'],
  'runtime-devices':['/usr/bin/xcrun','simctl','list','--json'],'build':build(derived),
  'create':['/usr/bin/xcrun','simctl','create',name,mapping['device_type'],mapping['runtime']],
  'boot':['/usr/bin/xcrun','simctl','boot',identity],'ready':['/usr/bin/xcrun','simctl','bootstatus',identity,'-b'],
  'seed':['/usr/bin/xcrun','simctl','addmedia',identity,str(work/'six-colors.png')],
  'device-shutdown':['/usr/bin/xcrun','simctl','shutdown',identity],
  'device-delete':['/usr/bin/xcrun','simctl','delete',identity]}
 for role in ('home','photo'):
  result_path=work/(role+'.xcresult')
  if role in result['results'] and result['results'][role]!=str(result_path):raise ValueError('Foreign result path')
  values[role]=test(role,identity,derived,result_path)
  values[role+'-summary']=['/usr/bin/xcrun','xcresulttool','get','test-results','summary','--path',str(result_path)]
  values[role+'-export']=['/usr/bin/xcrun','xcresulttool','export','attachments','--path',str(result_path),'--output-path',str(work/(role+'-export'))]
 return values
