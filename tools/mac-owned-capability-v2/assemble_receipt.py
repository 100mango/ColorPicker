"""Filesystem-only final 8KB receipt. Does not retry or observe any process."""
import hashlib,json,sys
from pathlib import Path
from preflight import read_bounded

def strict(raw):
 def pairs(items):
  out={}
  for k,v in items:
   if k in out:raise ValueError('duplicate key')
   out[k]=v
  return out
 return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite value')))
def assemble(meta,observed,sources):
 good=meta.get('complete') is True and observed.get('complete') is True and observed.get('leader_reaped') is True and observed.get('compiled_for_darwin_public_sdk') is True
 good=good and observed.get('scope')=='public_sdk_synthetic_capability_only' and observed.get('general_group_oracle_proven') is False and observed.get('unique_lifetime_identity_proven') is False
 phases=observed.get('phases',[])
 good=good and len(phases)==3
 if good:
  for row,(count,terminal,live) in zip(phases,((2,0,1),(2,1,1),(1,1,0))):
   good=good and all(type(row.get(k)) is int and row[k]==v for k,v in {'passed':1,'count':count,'terminal':terminal,'live_descendant':live}.items())
   good=good and type(row.get('returned_bytes')) is int and type(observed.get('pid_bytes')) is int and row['returned_bytes']==count*observed['pid_bytes']
 receipt={'schema':1,'complete':bool(good),'meaning':'measured public ABI and three synthetic observations only','preflight':meta,'observation':observed,'source_sha256':sources,'general_owned_runner_approved':False,'product_qualified':False}
 raw=(json.dumps(receipt,sort_keys=True,allow_nan=False)+'\n').encode()
 if len(raw)>8192:raise ValueError('receipt exceeds 8192 bytes')
 return raw
if __name__=='__main__':
 if sys.argv[1:]:raise SystemExit('no arguments')
 root=Path(__file__).resolve().parent
 paths=('owned_group_capability.c','preflight.py','assemble_receipt.py')
 sources={name:hashlib.sha256(read_bounded(root/name,32768)).hexdigest() for name in paths}
 meta=strict(read_bounded('build/capability-preflight.json',2048));observed=strict(read_bounded('build/capability-observation.json',4096))
 raw=assemble(meta,observed,sources);sys.stdout.buffer.write(raw)
 raise SystemExit(0 if strict(raw)['complete'] else 1)
