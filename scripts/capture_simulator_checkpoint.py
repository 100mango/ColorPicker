#!/usr/bin/env python3
"""Capture a held test-owned simulator checkpoint through supported simctl APIs."""
import json,os,subprocess,uuid
from pathlib import Path
from bounded_process import run_captured, check_output

_containers = {}
_bindings = {}

def _read_request(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError('Runner request is not an independent regular file')
    with path.open('rb') as stream: raw=stream.read(1025)
    if len(raw)>1024: raise ValueError('Runner request exceeds its bound')
    value=json.loads(raw)
    if not isinstance(value,dict): raise ValueError('Runner request must be an object')
    return value

def prime_container(device,runner_identifier,lease_id,device_root=None):
    """Bind a supported current-runner lookup to its fresh test-owned nonce."""
    if str(uuid.UUID(device)).upper()!=device or str(uuid.UUID(lease_id)).upper()!=lease_id:
        raise ValueError('Invalid exact device or runner lease UUID')
    if not runner_identifier.startswith('com.mango.touchColor.TouchColorVisionUITests'):
        raise ValueError('Unexpected runner product')
    raw=Path(check_output(['xcrun','simctl','get_app_container',device,runner_identifier,'data'],text=True,timeout=30).strip())
    root=Path(device_root) if device_root else Path.home()/'Library/Developer/CoreSimulator/Devices'
    expected=(root/device/'data/Containers/Data/Application').resolve(strict=True)
    if raw.is_symlink(): raise ValueError('Symlink runner container')
    container=raw.resolve(strict=True)
    if container.parent!=expected or not container.is_dir(): raise ValueError('Container belongs to another device/root')
    uuid.UUID(container.name)
    lease=container/'tmp'/('TouchColor-runner-'+lease_id+'.json')
    value=_read_request(lease)
    if value!={'id':lease_id,'runner':runner_identifier}: raise ValueError('Current runner nonce/product mismatch')
    info=container.stat();key=(device,runner_identifier)
    _containers[key]=container
    _bindings[key]={'lease':lease_id,'device':info.st_dev,'inode':info.st_ino}
    result={'success':True,'device':device,'runner':runner_identifier,'lease':lease_id,'container_id':container.name}
    # Finish the supported container lookup before XCTest opens the heavy Photos
    # service. The test verifies this fresh nonce instead of racing that lookup.
    publish_acknowledgement(lease.with_suffix('.ack'), result)
    return result

def _primed_container(device,runner_identifier):
    key=(device,runner_identifier);container=_containers.get(key);binding=_bindings.get(key)
    if container is None or binding is None: raise ValueError('No verified current runner cache')
    if container.is_symlink() or not container.is_dir(): raise ValueError('Runner container changed')
    info=container.stat()
    if (info.st_dev,info.st_ino)!=(binding['device'],binding['inode']): raise ValueError('Runner container identity changed')
    value=_read_request(container/'tmp'/('TouchColor-runner-'+binding['lease']+'.json'))
    if value!={'id':binding['lease'],'runner':runner_identifier}: raise ValueError('Runner lease changed or became stale')
    return container,binding['lease']

def publish_acknowledgement(destination, outcome):
    # XCTest treats existence as readiness. Publish a complete closed file with a
    # same-directory rename, so it can never observe an empty/partial JSON write.
    temporary = destination.with_name(destination.name + '.' + str(uuid.uuid4()) + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(outcome, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)

def fail_cached_capture(device, runner_identifier, request_id, reason,require_primed=False):
    """Acknowledge failure without launching a command on an unhealthy VM.

    Only a previously verified runner container can be used. If the runner was
    replaced and its request is absent there, report that limitation explicitly.
    """
    if str(uuid.UUID(request_id)).upper()!=request_id: raise ValueError('Invalid request UUID')
    outcome = {'id': request_id, 'success': False, 'error': reason[:500], 'acknowledged': False}
    container = _containers.get((device, runner_identifier))
    lease=None
    if require_primed:
        try: container,lease=_primed_container(device,runner_identifier)
        except (OSError,ValueError): return outcome
    if container is None: return outcome
    request = container / 'tmp' / ('TouchColor-capture-' + request_id + '.json')
    if not request.is_file() or request.stat().st_size > 1024: return outcome
    try: description = _read_request(request)
    except (OSError,ValueError): return outcome
    if require_primed and (description.get('runner')!=runner_identifier or description.get('lease')!=lease): return outcome
    if description.get('id') != request_id or not description.get('name', '').startswith('Native Vision'): return outcome
    outcome['acknowledged'] = True
    publish_acknowledgement(request.with_suffix('.ack'), outcome)
    return outcome

def capture(device,runner_identifier,request_id,output,may_start=lambda: True,require_primed=False):
    if str(uuid.UUID(request_id)).upper()!=request_id: raise ValueError('Invalid request UUID')
    if not may_start():
        return fail_cached_capture(device,runner_identifier,request_id,'No capture command: host lifecycle cleanup is unconfirmed',require_primed=require_primed)
    key=(device,runner_identifier)
    container=_containers.get(key)
    lease=None
    if require_primed: container,lease=_primed_container(device,runner_identifier)
    # Reuse only a previously discovered runner container holding this exact new UUID.
    # A changed/reinstalled runner requires a new supported simctl lookup.
    if not require_primed and (container is None or not (container/'tmp'/('TouchColor-capture-'+request_id+'.json')).is_file()):
        container=Path(check_output(['xcrun','simctl','get_app_container',device,runner_identifier,'data'],text=True,timeout=30).strip())
        _containers[key]=container
    request=container/'tmp'/('TouchColor-capture-'+request_id+'.json')
    ack=container/'tmp'/('TouchColor-capture-'+request_id+'.ack')
    outcome={'id':request_id,'success':False}
    validated_request=False
    try:
        description=_read_request(request)
        if description.get('id')!=request_id or not description.get('name','').startswith('Native Vision') or len(description.get('name',''))>140:
            raise ValueError('Capture request identity mismatch')
        if require_primed and (description.get('runner')!=runner_identifier or description.get('lease')!=lease):
            raise ValueError('Capture request does not match current runner binding')
        validated_request=True
        output=Path(output);output.mkdir(parents=True,exist_ok=True)
        # The test holds the same state until acknowledgement. A timed-out simctl
        # capture may leave pixels but is not a success. Retry that read-only
        # command once, with a distinct file so an old writer cannot race it.
        outcome['attempts']=[]
        for attempt in range(2):
            if not may_start():
                outcome['cleanup_unconfirmed']=True
                raise RuntimeError('No further capture command: host lifecycle cleanup is unconfirmed')
            destination=output/((request_id if attempt==0 else str(uuid.uuid4()).upper())+'.jpeg')
            command=['xcrun','simctl','io',device,'screenshot','--type=jpeg',str(destination)]
            try:
                result=run_captured(command,text=True,timeout=20)
                outcome['attempts'].append({'exit':result.returncode,'file':destination.name})
                break
            except subprocess.TimeoutExpired as error:
                outcome['attempts'].append({'exit':124,'file':destination.name,'error':str(error)[:1600]})
                if attempt==1 or not getattr(error,'cleanup_confirmed',False): raise
        # Nonzero returns (including permission errors) are never retried.
        outcome.update(command=command,exit=result.returncode,diagnostic=(result.stdout+result.stderr)[-1600:])
        if result.returncode!=0 or not destination.is_file(): raise RuntimeError('simctl screenshot did not produce an image')
        if destination.stat().st_size>3_000_000:
            destination.unlink();raise RuntimeError('Simulator checkpoint exceeds3 MB retention cap')
        outcome.update(success=True,file=destination.name,name=description['name'],bytes=destination.stat().st_size)
        manifest=output/'manifest.json'
        groups=json.loads(manifest.read_text()) if manifest.exists() else []
        groups.append({'source':'simctl io screenshot at held XCTest checkpoint','attachments':[{'exportedFileName':destination.name,'suggestedHumanReadableName':description['name']}]})
        manifest.write_text(json.dumps(groups,indent=2)+'\n')
    except Exception as error:
        outcome['error']=str(error)
        if isinstance(error, subprocess.TimeoutExpired) and not getattr(error, 'cleanup_confirmed', False):
            outcome['cleanup_unconfirmed']=True
    finally:
        if validated_request: publish_acknowledgement(ack, outcome)
    return outcome
