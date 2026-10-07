"""Closed reset-only receipt and existing-label observations; no application calls."""
import re
from pathlib import Path
import mac_passive_lifecycle as passive
from retain_mac_evidence import strict_json, read_file

CASE = passive.CASES[0]
ARGS = ['--ui-test-reset']
require = passive.require
integer = passive.integer
number = passive.number
digest = passive.digest


def reset_identities(root):
    summary = strict_json(read_file(root/'mac-ui-summary.json',512*1024))
    start,end = summary.get('startTime'),summary.get('finishTime')
    require(number(start) and number(end) and start<end,'reset-missing-result-interval')
    configs=summary.get('devicesAndConfigurations')
    require(isinstance(configs,list) and len(configs)==1,'reset-ambiguous-destination')
    config=configs[0];device=config.get('device',{})
    require(all(device.get(k)==v for k,v in {'platform':'macOS','architecture':'arm64','osVersion':'27.0'}.items()) and
        isinstance(device.get('deviceId'),str) and device['deviceId'] and
        config.get('testPlanConfiguration',{}).get('configurationName')=='Test Scheme Action','reset-wrong-destination')
    groups=strict_json(read_file(root/'screenshots/manifest.json',512*1024))
    require(isinstance(groups,list) and len(groups)==1,'reset-not-one-case')
    group=groups[0]
    require(group.get('testIdentifier')=='TouchColorMacUITests/'+CASE+'()' and
        group.get('testIdentifierURL')=='test://com.apple.xcode/TouchColorMac/TouchColorMacUITests/TouchColorMacUITests/'+CASE and
        isinstance(group.get('attachments'),list) and len(group['attachments'])<=512,'reset-foreign-case')
    matches=[]
    for item in group['attachments']:
        name=item.get('suggestedHumanReadableName','')
        require(isinstance(name,str),'reset-bad-attachment-name')
        if name.startswith(passive.ATTACHMENT):matches.append(item)
    require(len(matches)==1,'reset-not-one-receipt')
    item=matches[0];filename=item.get('exportedFileName','')
    require(isinstance(filename,str) and re.fullmatch('[0-9A-Fa-f-]{36}\\.txt',filename),'reset-bad-receipt-path')
    raw=read_file(root/'screenshots'/filename,4096);row=strict_json(raw)
    fields={'v','token','pid','test','ordinal','started','captured','args','sandbox','bundle','applicationPath',
        'expectedPath','executable','executableSHA256','logicSHA256','xctestPID','xctestPIDReason'}
    require(isinstance(row,dict) and set(row)==fields and type(row['v']) is int and row['v']==1,'reset-bad-receipt-fields')
    require(row['test']=='-[TouchColorMacUITests '+CASE+']' and type(row['ordinal']) is int and row['ordinal']==1 and
        integer(row['pid'],1) and passive.valid_uuid(row['token']) and row['sandbox'] is False and row['args']==ARGS,'reset-wrong-launch-input')
    require(passive.identity_scope(group,item)=={'case':CASE,'token':row['token'],'ordinal':1},'reset-unbound-identity-title')
    require(number(row['started']) and number(row['captured']) and start<=row['started']<=row['captured']<=end and
        number(item.get('timestamp')) and row['captured']<=item['timestamp']+.001 and item['timestamp']<=end+.001,'reset-stale-receipt')
    require(item.get('deviceId')==device['deviceId'] and item.get('configurationName')=='Test Scheme Action','reset-foreign-attachment-destination')
    app=row['applicationPath']
    require(row['bundle']=='com.mango.touchColor' and app==row['expectedPath'] and isinstance(app,str) and len(app)<=768 and
        app.startswith('/') and app.endswith('/build/mac-tests/Build/Products/Debug/TouchColor.app') and '..' not in Path(app).parts and
        row['executable']==app+'/Contents/MacOS/TouchColor','reset-wrong-product-path')
    require(all(isinstance(row[k],str) and re.fullmatch('[0-9a-f]{64}',row[k]) for k in ('executableSHA256','logicSHA256')),'reset-missing-product-hashes')
    require(row['xctestPID'] is None and row['xctestPIDReason']=='No public PID query; correlate retained failure hierarchy independently','reset-invented-xctest-pid')
    row.update(case=CASE,result_start=start,result_end=end,receipt_sha256=digest(raw),receipt_file='screenshots/'+filename)
    return [row]


def parse_runner_locale(raw):
    require(len(raw)<=4096,'runner-locale-byte-cap')
    value=strict_json(raw)
    require(isinstance(value,dict) and set(value)=={'localeIdentifier','preferredLanguages'},'runner-locale-fields')
    require(isinstance(value['localeIdentifier'],str) and re.fullmatch('[A-Za-z0-9_@.=;:+-]{1,256}',value['localeIdentifier']), 'runner-locale-identifier')
    languages=value['preferredLanguages']
    require(isinstance(languages,list) and 1<=len(languages)<=16 and
        all(isinstance(x,str) and re.fullmatch('[A-Za-z0-9_-]{1,64}',x) for x in languages) and len(set(languages))==len(languages),'runner-preferred-languages')
    return value


OWNED_LABELS={
    'english-strings': ('Sample','Open Image or Palette…','Export Palette…','Save Color'),
    'simplified-chinese-strings': ('取色','打开图片或调色板…','导出调色板…','保存颜色')}


def app_language_observation(summary, contact):
    result=dict(observation='unknown',basis='unavailable-existing-app-evidence',observedLabels=[],effectiveLocale='unknown')
    if contact is None:return result
    if contact['outcome']=='passed':
        # The unchanged case's exact English contact.label assertion completed.
        return dict(observation='english-strings',basis='unchanged-English-contact-label-assertion-passed',
            observedLabels=['Contact the developer about privacy'],effectiveLocale='unknown')
    failures=summary.get('testFailures',[])
    if len(failures)!=1:return result
    text=failures[0].get('failureText','');pid=contact['identity']['pid']
    if not isinstance(text,str) or text.count('Attributes: Application,')!=1 or text.count('Element subtree:\n')!=1 or text.count('Path to element:\n')!=1:return result
    owner=r"Application, [^\n]*pid: "+str(pid)+r", title: 'TouchColor'(?:,|$)"
    header=re.search(r"Attributes: "+owner,text)
    begin=text.index('Element subtree:\n')+len('Element subtree:\n');end=text.index('Path to element:\n')
    if header is None or header.end()>begin or end<=begin:return result
    subtree=text[begin:end];lines=[line for line in subtree.splitlines() if line.strip()]
    roots=re.findall(r'(?m)^\s*→?Application,[^\n]*',subtree)
    if not lines or len(roots)!=1 or re.fullmatch(r'\s*→?'+owner+r'[^\n]*',lines[0]) is None:return result
    root_indent=len(lines[0])-len(lines[0].lstrip())
    owned_lines='\n'.join(line for line in lines[1:] if len(line)-len(line.lstrip())>root_indent)
    found={language:[label for label in labels if re.search(r"(?m)^\s*(?:MenuBarItem|MenuItem), [^\n]*title: '"+re.escape(label)+r"'(?:,|$)",owned_lines)]
        for language,labels in OWNED_LABELS.items()}
    result['observedLabels']=[label for labels in found.values() for label in labels]
    if result['observedLabels']:result['basis']='existing-bound-app-failure-hierarchy'
    if all(found.values()):result['observation']='mixed-observed-strings'
    else:
        for language,labels in found.items():
            if len(labels)>=2:result['observation']=language
    return result


def validate_reset_contact(root, product, command_exit):
    summary = strict_json(read_file(root / 'mac-ui-summary.json', 512 * 1024))
    require(isinstance(summary, dict), 'bad-contact-summary')
    for key in ('passedTests', 'failedTests', 'skippedTests', 'expectedFailures', 'totalTestCount'):
        require(integer(summary.get(key)), 'missing-case-count')
    require(summary['totalTestCount'] == 1 and summary['skippedTests'] == 0 and summary['expectedFailures'] == 0 and
        summary['passedTests'] + summary['failedTests'] == 1, 'not-exact-single-case')
    passed = summary['passedTests'] == 1
    require(summary.get('result') == ('Passed' if passed else 'Failed') and command_exit == (0 if passed else 65), 'contradictory-test-outcome')
    failures = summary.get('testFailures', [])
    require(isinstance(failures, list) and len(failures) == (0 if passed else 1), 'unknown-failure-count')
    for row in failures:
        require(isinstance(row, dict) and row.get('testIdentifierString') == 'TouchColorMacUITests/' + CASE + '()' and row.get('testIdentifierURL') == 'test://com.apple.xcode/TouchColorMac/TouchColorMacUITests/TouchColorMacUITests/' + CASE, 'foreign-failure')
        require(row.get('targetName')=='TouchColorMacUITests' and row.get('testName')==CASE+'()' and
            integer(row.get('testIdentifier'),1) and isinstance(row.get('failureText'),str) and
            re.match(r'^XCTAssert(?:True|Equal) failed(?: -|:)',row['failureText']), 'not-known-assertion-failure')
    configs=summary.get('devicesAndConfigurations')
    require(isinstance(configs,list) and len(configs)==1 and
        all(configs[0].get(k)==summary[k] and type(configs[0].get(k)) is int for k in ('passedTests','failedTests','skippedTests','expectedFailures')), 'contradictory-device-outcome')
    rows = reset_identities(root)
    require(len(rows) == 1 and rows[0]['case'] == CASE and rows[0]['ordinal'] == 1 and rows[0]['sandbox'] is False, 'missing-exact-receipt')
    identity = rows[0]
    require(all(identity[k] == v for k, v in product.items()), 'contact-product-mismatch')
    groups = strict_json(read_file(root / 'screenshots/manifest.json', 512 * 1024))
    require(len(groups) == 1 and groups[0]['testIdentifier'] == 'TouchColorMacUITests/' + CASE + '()', 'foreign-export-case')
    return {'outcome': 'passed' if passed else 'failed', 'identity': identity,
        'summarySHA256': digest(read_file(root / 'mac-ui-summary.json', 512 * 1024)),
        'manifestSHA256': digest(read_file(root / 'screenshots/manifest.json', 512 * 1024))}
