#!/usr/bin/env python3
"""Capture a held test-owned simulator checkpoint through supported simctl APIs."""
import json,subprocess,uuid
from pathlib import Path

_containers = {}

def capture(device,runner_identifier,request_id,output):
    assert str(uuid.UUID(request_id)).upper()==request_id
    key=(device,runner_identifier)
    container=_containers.get(key)
    # Reuse only a previously discovered runner container holding this exact new UUID.
    # A changed/reinstalled runner requires a new supported simctl lookup.
    if container is None or not (container/'tmp'/('TouchColor-capture-'+request_id+'.json')).is_file():
        container=Path(subprocess.check_output(['xcrun','simctl','get_app_container',device,runner_identifier,'data'],text=True,timeout=30).strip())
        _containers[key]=container
    request=container/'tmp'/('TouchColor-capture-'+request_id+'.json')
    ack=container/'tmp'/('TouchColor-capture-'+request_id+'.ack')
    outcome={'id':request_id,'success':False}
    try:
        description=json.loads(request.read_text())
        assert description['id']==request_id and description['name'].startswith('Native Vision') and len(description['name'])<=140
        output=Path(output);output.mkdir(parents=True,exist_ok=True)
        # The test holds the same state until acknowledgement. A timed-out simctl
        # capture may leave pixels but is not a success. Retry that read-only
        # command once, with a distinct file so an old writer cannot race it.
        outcome['attempts']=[]
        for attempt in range(2):
            destination=output/((request_id if attempt==0 else str(uuid.uuid4()).upper())+'.jpeg')
            command=['xcrun','simctl','io',device,'screenshot','--type=jpeg',str(destination)]
            try:
                result=subprocess.run(command,capture_output=True,text=True,timeout=20)
                outcome['attempts'].append({'exit':result.returncode,'file':destination.name})
                break
            except subprocess.TimeoutExpired as error:
                outcome['attempts'].append({'exit':124,'file':destination.name,'error':str(error)[:1600]})
                if attempt==1: raise
        # Nonzero returns (including permission errors) are never retried.
        outcome.update(command=command,exit=result.returncode,diagnostic=(result.stdout+result.stderr)[-1600:])
        assert result.returncode==0 and destination.is_file(), 'simctl screenshot did not produce an image'
        if destination.stat().st_size>3_000_000:
            destination.unlink();raise RuntimeError('Simulator checkpoint exceeds3 MB retention cap')
        outcome.update(success=True,file=destination.name,name=description['name'],bytes=destination.stat().st_size)
        manifest=output/'manifest.json'
        groups=json.loads(manifest.read_text()) if manifest.exists() else []
        groups.append({'source':'simctl io screenshot at held XCTest checkpoint','attachments':[{'exportedFileName':destination.name,'suggestedHumanReadableName':description['name']}]})
        manifest.write_text(json.dumps(groups,indent=2)+'\n')
    except Exception as error:outcome['error']=str(error)
    finally:
        ack.write_text(json.dumps(outcome))
    return outcome
