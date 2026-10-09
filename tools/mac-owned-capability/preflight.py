"""Read-only capability metadata. Does not spawn or signal any process."""
import hashlib,json,os,plistlib,re,stat,sys
from pathlib import Path
PAIRS={('27.0','26A428'),('27.0.1','26A434')}

def read_bounded(path,cap):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size>cap:raise ValueError('unsafe input')
        raw=b''
        while len(raw)<=cap:
            part=os.read(fd,min(4096,cap+1-len(raw)))
            if not part:break
            raw+=part
        after=os.fstat(fd)
        if len(raw)>cap or (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('changed/oversized input')
        return raw
    finally:os.close(fd)

def assess(host,xcode,machine,system,version,capabilities,sha):
    record={'schema':1,'scope':'synthetic_public_sdk_capability_only','product_sha':'7c671f04e4d69884741a411851ae26083361c7f7',
        'control_sha':sha,'host_version':host.get('ProductVersion'),'host_build':host.get('ProductBuildVersion'),
        'architecture':machine,'system':system,'xcode_lines':xcode.splitlines(),'python_version':list(version),
        'python_waitid_attributes':capabilities,'complete':False,'native_product_qualification':False}
    record['complete']=((record['host_version'],record['host_build']) in PAIRS and machine=='arm64' and system=='Darwin'
        and xcode.splitlines()==['Xcode 27.0','Build version 27A266a'] and re.fullmatch('[0-9a-f]{40}',sha) is not None
        and set(capabilities)=={'waitid','P_PID','WEXITED','WNOHANG','WNOWAIT'} and all(v is True for v in capabilities.values()))
    return record

def main():
    if sys.argv[1:]!=['build/capability-xcode.txt']:raise SystemExit('exact input path required')
    host=plistlib.loads(read_bounded('/System/Library/CoreServices/SystemVersion.plist',8192))
    xcode=read_bounded(sys.argv[1],256).decode('ascii')
    info=os.uname();capabilities={name:hasattr(os,name) for name in ('waitid','P_PID','WEXITED','WNOHANG','WNOWAIT')}
    record=assess(host,xcode,info.machine,info.sysname,sys.version_info[:3],capabilities,os.environ.get('GITHUB_SHA',''))
    raw=(json.dumps(record,sort_keys=True)+'\n').encode()
    if len(raw)>2048:raise ValueError('metadata oversized')
    sys.stdout.buffer.write(raw)
    return 0 if record['complete'] else 1
if __name__=='__main__':raise SystemExit(main())
