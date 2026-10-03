#!/usr/bin/env python3
"""Read actual XCTest SDK availability before adopting platform-specific native audits.
Typechecking here is not an accessibility pass; runtime audits remain a separate gate.
"""
import json,subprocess
from pathlib import Path
from bounded_process import run_captured, check_output
out=Path('build/accessibility-api');out.mkdir(parents=True,exist_ok=True)
source=out/'AuditProbe.swift'
source.write_text('import XCTest\n@MainActor func audit(_ app: XCUIApplication) throws { try app.performAccessibilityAudit(for: .all) { issue in print(issue.compactDescription); return false } }\n')
rows=[]
for sdk,target in [('macosx','arm64-apple-macosx27.0'),('xrsimulator','arm64-apple-xros27.0-simulator'),('watchsimulator','arm64-apple-watchos27.0-simulator'),('appletvsimulator','arm64-apple-tvos27.0-simulator')]:
    try:
        platform=Path(check_output(['xcrun','--sdk',sdk,'--show-sdk-platform-path'],text=True,timeout=20).strip())
        sdkpath=check_output(['xcrun','--sdk',sdk,'--show-sdk-path'],text=True,timeout=20).strip()
        command=['xcrun','--sdk',sdk,'swiftc','-typecheck','-sdk',sdkpath,'-target',target,'-F',str(platform/'Developer/Library/Frameworks'),'-I',str(platform/'Developer/usr/lib'),'-module-cache-path',str(out/sdk),str(source)]
        result=run_captured(command,stderr=subprocess.STDOUT,text=True,timeout=90)
        row={'sdk':sdk,'exit':result.returncode,'diagnostic':result.stdout[-10000:],'scope':'typecheck only; not a runtime audit'}
    except Exception as error:row={'sdk':sdk,'error':str(error),'cleanup_unconfirmed':isinstance(error,subprocess.TimeoutExpired) and not getattr(error,'cleanup_confirmed',False),'scope':'probe setup unresolved; no API availability inference'}
    rows.append(row);print(json.dumps(row),flush=True)
    if row.get('cleanup_unconfirmed'):break
(out/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
