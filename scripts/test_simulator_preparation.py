"""Execute the real preparation branches with a temporary synthetic simctl."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class SimulatorPreparationTests(unittest.TestCase):
    def prepare(self, mode, app_exists=True):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); binary=root/'bin'; binary.mkdir()
            trace=root/'commands.jsonl'
            fake=binary/'xcrun'
            fake.write_text('#!'+sys.executable+'\n'+'''import json,os,sys
from pathlib import Path
args=sys.argv[1:]
with open(os.environ['TC_SYNTHETIC_TRACE'],'a') as stream: stream.write(json.dumps(args)+'\\n')
if args==['simctl','list','devices','available','-j']:
 print(json.dumps({'devices':{'com.apple.CoreSimulator.SimRuntime.iOS-27-0':[{'name':'TouchColor Compact SE3','udid':'synthetic-owned-phone','isAvailable':True}]}}))
elif args==['simctl','list','devicetypes','-j']:
 print(json.dumps({'devicetypes':[{'name':'iPhone SE (3rd generation)','identifier':'synthetic-phone-type'}]}))
elif args[:2]==['simctl','install']:
 if not Path(args[-1]).is_dir(): raise SystemExit(2)
elif args[:2] not in [['simctl','boot'],['simctl','bootstatus'],['simctl','launch'],['simctl','terminate']]:
 raise SystemExit('Unexpected command '+str(args))
''')
            fake.chmod(0o700)
            # Isolate only the shell's fixed temporary inventory path. Its real
            # branch selection and required install/launch commands execute.
            source=Path(__file__).with_name('test_simulators.sh').read_text()
            script=root/'prepare.sh'; script.write_text(source.replace('/tmp/touchcolor-devices.json',str(root/'devices.json')))
            if app_exists: (root/'build/simulator/Build/Products/Debug-iphonesimulator/TouchColor.app').mkdir(parents=True)
            env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'TC_SYNTHETIC_TRACE':str(trace)}
            result=subprocess.run(['bash',str(script),'iPhoneCompact',mode],cwd=root,env=env,capture_output=True,text=True,timeout=10)
            calls=[json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
            identity=root/'build/iPhoneCompact-simulator.json'
            return result,calls,json.loads(identity.read_text()) if identity.is_file() else None

    def test_explicit_unit_preparation_requires_app_but_not_files_fixture(self):
        result,calls,identity=self.prepare('prepare-unit')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(identity['udid'],'synthetic-owned-phone')
        self.assertEqual(identity['runtime'],'com.apple.CoreSimulator.SimRuntime.iOS-27-0')
        self.assertIn(['simctl','terminate','synthetic-owned-phone','com.mango.touchColor'],calls)
        self.assertFalse(any('PaletteFixtures' in str(call) for call in calls))
        result,_,_=self.prepare('prepare-unit',app_exists=False)
        self.assertNotEqual(result.returncode,0)

    def test_full_preparation_still_fails_when_required_fixture_is_missing(self):
        result,calls,_=self.prepare('prepare')
        self.assertEqual(result.returncode,2)
        self.assertEqual(calls[-1],['simctl','install','synthetic-owned-phone','build/palette-fixtures/Build/Products/Debug-iphonesimulator/PaletteFixtures.app'])


if __name__=='__main__': unittest.main()
