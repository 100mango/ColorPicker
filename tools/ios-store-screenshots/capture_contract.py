"""Pure native capture identity, PNG and result readers; no process execution."""
import struct,uuid
PRODUCT='922eb296e3b2417a414b72ad4eb2dddeb534328f'
TREE='4974b9ac597a75ef30dcf92be143da1441801db2'
RUNTIME='com.apple.CoreSimulator.SimRuntime.iOS-27-0'
RUNTIME_BUILD='24A434'
METHODS={
 'home':'TouchColorUITests/TouchColorOriginalDesignUITests/testOriginalHomeTabsAndRepeatedPhotoPickerCancellation',
 'photo-history':'TouchColorUITests/TouchColorOriginalDesignUITests/testRealPhotoSaveRelaunchDelete',
}
IMAGES={'home':'01-original-home','photo':'03-original-photo-sampled','history':'04-original-saved-library'}
ROWS={
 'iphone17pro':{'name':'iPhone 17 Pro','type':'com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro','size':(1206,2622)},
 'ipad13m5':{'name':'iPad Pro 13-inch (M5)','type':'com.apple.CoreSimulator.SimDeviceType.iPad-Pro-13-inch-M5-12GB','size':(2064,2752)},
}
def choose_device(runtime_rows,device_rows,lane):
 row=ROWS[lane]
 matches=[r for r in runtime_rows if r.get('identifier')==RUNTIME and r.get('isAvailable') is True and r.get('version')=='27.0' and r.get('buildversion')==RUNTIME_BUILD]
 if len(matches)!=1:raise ValueError('Exact available iOS runtime is required')
 supported=[d for d in matches[0].get('supportedDeviceTypes',[]) if d.get('identifier')==row['type'] and d.get('name')==row['name']]
 devices=[d for d in device_rows if d.get('identifier')==row['type'] and d.get('name')==row['name']]
 if len(supported)!=1 or len(devices)!=1:raise ValueError('Exact device must be installed and runtime-supported')
 return {'device_name':row['name'],'device_type':row['type'],'runtime':RUNTIME,'runtime_build':RUNTIME_BUILD,'expected_png_size':list(row['size'])}
def existing_device_ids(metadata):
 rows=metadata.get('devices')
 if not isinstance(rows,dict) or len(rows)>128:raise ValueError('Missing/bounded pre-create device inventory required')
 seen=set()
 for runtime,devices in rows.items():
  if not isinstance(runtime,str) or not runtime or not isinstance(devices,list):raise ValueError('Malformed pre-create inventory')
  for device in devices:
   if not isinstance(device,dict) or not isinstance(device.get('udid'),str):raise ValueError('Malformed existing device identity')
   value=device['udid']
   if str(uuid.UUID(value)).upper()!=value or value in seen or len(seen)>=2048:raise ValueError('Ambiguous pre-create device inventory')
   seen.add(value)
 return seen
def capture_dimensions(raw,lane):
 if len(raw)<33 or len(raw)>2*1024*1024 or raw[:8]!=b'\x89PNG\r\n\x1a\n' or raw[8:16]!=b'\0\0\0\rIHDR':raise ValueError('Expected original bounded PNG')
 size=struct.unpack('>II',raw[16:24])
 if size!=ROWS[lane]['size']:raise ValueError('Actual native dimensions differ; never rescale')
 return size

# Full Store-PNG validation operates only on original bytes. No conversion.
import zlib,math,re,time,json,hashlib

def png_complete(raw,lane,*,deadline,clock=time.monotonic):
 size=capture_dimensions(raw,lane);width,height=size;offset=8;seen=[];compressed=bytearray();ended=False
 def fence():
  if clock()>=deadline:raise TimeoutError('PNG validation deadline')
 while offset<len(raw):
  fence()
  if offset+12>len(raw):raise ValueError('Truncated PNG chunk')
  length=struct.unpack('>I',raw[offset:offset+4])[0];tag=raw[offset+4:offset+8];end=offset+12+length
  if end>len(raw):raise ValueError('PNG chunk exceeds original bytes')
  if re.fullmatch(b'[A-Za-z]{4}',tag) is None or tag[2]&32:raise ValueError('Invalid PNG chunk type')
  data=raw[offset+8:offset+8+length];crc=struct.unpack('>I',raw[end-4:end])[0]
  if zlib.crc32(tag+data)&0xffffffff!=crc:raise ValueError('PNG CRC differs')
  if tag==b'IHDR':
   if seen or length!=13 or data[8:]!=bytes([8,2,0,0,0]):raise ValueError('Only original noninterlaced8-bitRGB/noalpha PNG accepted')
  elif tag==b'tRNS':raise ValueError('PNG transparency forbidden')
  elif tag==b'IDAT':
   if not seen or (b'IDAT' in seen and seen[-1]!=b'IDAT'):raise ValueError('Invalid PNG IDAT ordering')
   compressed.extend(data)
  elif tag==b'IEND':
   if length or b'IDAT' not in seen or end!=len(raw):raise ValueError('Invalid PNG end')
   ended=True
  elif not (tag[0]&32):raise ValueError('Unknown/unapproved critical PNG chunk')
  seen.append(tag);offset=end
 if not ended or not compressed:raise ValueError('Incomplete PNG')
 fence();expected=(1+width*3)*height;decoder=zlib.decompressobj();pixels=decoder.decompress(compressed,expected+1)
 if len(pixels)!=expected or not decoder.eof or decoder.unconsumed_tail or decoder.unused_data:raise ValueError('Invalid bounded PNG scanlines')
 for row in range(height):
  fence()
  if pixels[row*(1+width*3)]>4:raise ValueError('Invalid PNG filter')
 return {'width':width,'height':height,'color_type':2,'bit_depth':8,'alpha':False,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}

def bind_summary(value,record,device,lane):
 expected={'totalTestCount':1,'passedTests':1,'failedTests':0,'skippedTests':0,'expectedFailures':0}
 if value.get('result')!='Passed' or record['exit']!=0 or any(type(value.get(k)) is not int or value[k]!=n for k,n in expected.items()):raise ValueError('Exact selected1/1 zero-failure summary required')
 begin,end=value.get('startTime'),value.get('finishTime')
 if any(type(n) not in (float,int) or not math.isfinite(n) for n in (begin,end)) or not record['started_epoch']<=begin<=end<=record['finished_epoch']:raise ValueError('Foreign/stale result time')
 rows=value.get('devicesAndConfigurations')
 if not isinstance(rows,list) or len(rows)!=1:raise ValueError('Ambiguous result device')
 row=rows[0];actual=row.get('device',{})
 expected_device={'deviceId':device['uuid'],'deviceName':device['owned_name'],'modelName':ROWS[lane]['name'],'osVersion':'27.0','osBuildNumber':RUNTIME_BUILD,'platform':'iOS Simulator','architecture':'arm64'}
 if any(actual.get(k)!=v for k,v in expected_device.items()):raise ValueError('Actual destination differs')
 if row.get('testPlanConfiguration')!={'configurationId':'1','configurationName':'Test Scheme Action'}:raise ValueError('Unexpected test configuration')
 if any(type(row.get(k)) is not int or row[k]!=n for k,n in expected.items() if k!='totalTestCount'):raise ValueError('Result device counts differ')
 return expected

def bind_cases(raw,role):
 method=METHODS['home' if role=='home' else 'photo-history'].rsplit('/',1)[1]
 pattern=re.compile(r"^Test Case '-\[TouchColorOriginalDesignUITests "+method+r"\]' (started|passed)(?:\.| \([0-9.]+ seconds\)\.)$")
 events=[]
 for line in raw.decode('utf-8').splitlines():
  if re.search(r'ORIGINAL_DESIGN_UNHANDLED_SYSTEM_PROMPT|\b(?:testing (?:failed|cancelled|canceled)|test (?:execute )?(?:failed|cancelled|canceled|interrupted)|fatal error|uncaught exception|permission denied|operation not permitted|operation (?:cancelled|canceled)|timed out)\b',line,re.I):raise ValueError('Native failure/cancellation/interruption marker')
  if line.startswith('Test Case '):
   match=pattern.fullmatch(line)
   if match is None:raise ValueError('Foreign/failing raw case')
   events.append(match.group(1))
 if events!=['started','passed']:raise ValueError('Missing/duplicate/out-of-order selected method')
 return {'method':method,'events':events,'full_log_sha256':hashlib.sha256(raw).hexdigest(),'full_log_bytes':len(raw)}
