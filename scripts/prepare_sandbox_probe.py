#!/usr/bin/env python3
"""Fresh synthetic boundary fixture prepared by the ordinary, unsandboxed CI host."""
import json,os,sys,tempfile
from pathlib import Path
record=Path(sys.argv[1]);record.parent.mkdir(parents=True,exist_ok=True)
folder=Path(tempfile.mkdtemp(prefix='TouchColor-boundary-',dir=os.environ['RUNNER_TEMP']))
os.chmod(folder,0o700)
file=folder/'unselected.txt';file.write_bytes(b'TouchColor synthetic boundary witness');os.chmod(file,0o600)
assert file.read_bytes()==b'TouchColor synthetic boundary witness'
file.write_bytes(b'TouchColor synthetic host write control')
assert file.read_bytes()==b'TouchColor synthetic host write control'
assert (folder.stat().st_mode&0o777)==0o700 and (file.stat().st_mode&0o777)==0o600
record.write_text(json.dumps({'file':str(file),'uid':os.geteuid(),'readControl':True,'writeControl':True})+'\n')
print('Unsandboxed same-user host read/write controls passed; fresh never-selected0700/0600 fixture')
