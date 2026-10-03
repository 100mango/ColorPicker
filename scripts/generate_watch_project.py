#!/usr/bin/env python3
"""Native watchOS executable and XCTest project, local packages only; no signing resource changes."""
from pathlib import Path
import hashlib, json, xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
objects={}
def uid(key): return hashlib.sha1(('watch:'+key).encode()).hexdigest()[:24].upper()
def add(key,isa,**fields):
    identifier=uid(key); objects[identifier]=dict(isa=isa,**fields); return identifier
def ref(path,kind): return add('file:'+path,'PBXFileReference',lastKnownFileType=kind,path=path,sourceTree='<group>')
def phase(name,kind,refs): return add(name,kind,buildActionMask=2147483647,files=[add(name+':'+r,'PBXBuildFile',fileRef=r) for r in refs],runOnlyForDeploymentPostprocessing=0)
def configs(name,settings):
    result=[]
    for config in ('Debug','Release'):
        values=dict(settings)
        values.update(ONLY_ACTIVE_ARCH='YES' if config=='Debug' else 'NO',SWIFT_OPTIMIZATION_LEVEL='-Onone' if config=='Debug' else '-O',SWIFT_ACTIVE_COMPILATION_CONDITIONS='DEBUG' if config=='Debug' else '',ENABLE_TESTABILITY='YES' if config=='Debug' else 'NO',DEBUG_INFORMATION_FORMAT='dwarf' if config=='Debug' else 'dwarf-with-dsym')
        result.append(add(name+config,'XCBuildConfiguration',name=config,buildSettings=values))
    return add(name+'configs','XCConfigurationList',buildConfigurations=result,defaultConfigurationIsVisible=0,defaultConfigurationName='Release')
allrefs=[]
def sources(directory):
    result=[ref(str(p.relative_to(ROOT)),'sourcecode.swift') for p in sorted((ROOT/directory).rglob('*.swift'))]
    allrefs.extend(result); return result
apprefs=sources('TouchColorWatch')
unitrefs=sources('TouchColorWatchTests')+sources('Packages/ColorCore/Tests')
uirefs=sources('TouchColorWatchUITests')
resource=ref('TouchColorWatch/Assets.xcassets','folder.assetcatalog')
privacy=ref('ColorPicker/PrivacyInfo.xcprivacy','text.xml')
localizations=[add('loc:'+lang,'PBXFileReference',lastKnownFileType='text.plist.strings',name=lang,path='TouchColorWatch/'+lang+'.lproj/Localizable.strings',sourceTree='<group>') for lang in ['en','zh-Hans']]
strings=add('strings','PBXVariantGroup',children=localizations,name='Localizable.strings',sourceTree='<group>')
infoLocalizations=[add('infoLoc:'+lang,'PBXFileReference',lastKnownFileType='text.plist.strings',name=lang,path='TouchColorWatch/'+lang+'.lproj/InfoPlist.strings',sourceTree='<group>') for lang in ['en','zh-Hans']]
infoStrings=add('infoStrings','PBXVariantGroup',children=infoLocalizations,name='InfoPlist.strings',sourceTree='<group>')
package=add('ColorCorePackage','XCLocalSwiftPackageReference',relativePath='Packages/ColorCore')
products=[]; targets=[]; testattrs={}
for name,kind,files in [('TouchColorWatch','application',apprefs),('TouchColorWatchTests','bundle.unit-test',unitrefs),('TouchColorWatchUITests','bundle.ui-testing',uirefs)]:
    app=kind=='application'
    product=add(name+'product','PBXFileReference',explicitFileType='wrapper.application' if app else 'wrapper.cfbundle',includeInIndex=0,path='TouchColor.app' if app else name+'.xctest',sourceTree='BUILT_PRODUCTS_DIR'); products.append(product)
    modules=[]; links=[]
    if kind!='bundle.ui-testing':
        for module in ['ColorDomain','ColorRaster','ColorPaletteLegacy']:
            dep=add(name+module,'XCSwiftPackageProductDependency',productName=module)
            modules.append(dep); links.append(add(name+'link'+module,'PBXBuildFile',productRef=dep))
    framework=add(name+'frameworks','PBXFrameworksBuildPhase',buildActionMask=2147483647,files=links,runOnlyForDeploymentPostprocessing=0)
    phases=[phase(name+'sources','PBXSourcesBuildPhase',files),framework,phase(name+'resources','PBXResourcesBuildPhase',[resource,privacy,strings,infoStrings] if app else [])]
    settings=dict(PRODUCT_NAME='$(TARGET_NAME)',PRODUCT_BUNDLE_IDENTIFIER='com.mango.touchColor.watchkitapp' if app else 'com.mango.touchColor.'+name,GENERATE_INFOPLIST_FILE='YES',WATCHOS_DEPLOYMENT_TARGET='9.0',SDKROOT='watchos',SUPPORTED_PLATFORMS='watchos watchsimulator',TARGETED_DEVICE_FAMILY='4',SUPPORTS_MACCATALYST='NO',SWIFT_VERSION='5.0',CODE_SIGN_STYLE='Automatic',CODE_SIGNING_ALLOWED='NO',ENABLE_APP_SANDBOX='NO',ENABLE_HARDENED_RUNTIME='NO',LD_RUNPATH_SEARCH_PATHS=['$(inherited)','@executable_path/Frameworks','@loader_path/Frameworks'],CLANG_ENABLE_MODULES='YES')
    if app:
        settings.update(PRODUCT_NAME='TouchColor',PRODUCT_MODULE_NAME='TouchColorWatch',INFOPLIST_KEY_CFBundleName='TouchColor',INFOPLIST_KEY_CFBundleDisplayName='TouchColor',INFOPLIST_KEY_WKApplication='YES',INFOPLIST_KEY_WKCompanionAppBundleIdentifier='com.mango.touchColor',INFOPLIST_KEY_WKRunsIndependentlyOfCompanionApp='YES',ASSETCATALOG_COMPILER_APPICON_NAME='AppIcon',MARKETING_VERSION='2.0',CURRENT_PROJECT_VERSION='20001')
    if kind=='bundle.unit-test': settings.update(TEST_HOST='$(BUILT_PRODUCTS_DIR)/TouchColor.app/TouchColor',BUNDLE_LOADER='$(TEST_HOST)')
    if kind=='bundle.ui-testing': settings.update(TEST_TARGET_NAME='TouchColorWatch')
    dependencies=[]
    if not app:
        # Xcode27's XCTest/XCUIAutomation require watchOS10. Keep the actual
        # Watch app's deployment target at9; only test bundles use the SDK floor.
        settings['WATCHOS_DEPLOYMENT_TARGET']='10.0'
        proxy=add(name+'proxy','PBXContainerItemProxy',containerPortal=uid('Project'),proxyType=1,remoteGlobalIDString=uid('TouchColorWatch'),remoteInfo='TouchColorWatch')
        dependencies=[add(name+'dependency','PBXTargetDependency',target=uid('TouchColorWatch'),targetProxy=proxy)]
        testattrs[uid(name)]=dict(TestTargetID=uid('TouchColorWatch'))
    targets.append(add(name,'PBXNativeTarget',buildConfigurationList=configs(name,settings),buildPhases=phases,buildRules=[],dependencies=dependencies,name=name,productName=name,productReference=product,productType='com.apple.product-type.'+kind,packageProductDependencies=modules))
productgroup=add('Products','PBXGroup',children=products,name='Products',sourceTree='<group>')
group=add('MainGroup','PBXGroup',children=allrefs+[resource,privacy,strings,infoStrings,productgroup],sourceTree='<group>')
add('Project','PBXProject',attributes=dict(LastUpgradeCheck='2700',TargetAttributes=testattrs),buildConfigurationList=configs('Project',dict(SWIFT_VERSION='5.0',WATCHOS_DEPLOYMENT_TARGET='9.0',SDKROOT='watchos',CLANG_ENABLE_MODULES='YES',CLANG_ENABLE_OBJC_ARC='YES',GCC_C_LANGUAGE_STANDARD='gnu17',ENABLE_USER_SCRIPT_SANDBOXING='YES')),compatibilityVersion='Xcode 14.0',developmentRegion='en',hasScannedForEncodings=0,knownRegions=['en','zh-Hans','Base'],mainGroup=group,productRefGroup=productgroup,projectDirPath='',projectRoot='',targets=targets,packageReferences=[package])
def serialize(value,level=0):
    indent='\t'*level
    if isinstance(value,dict): return '{\n'+''.join(indent+'\t'+json.dumps(str(k))+' = '+serialize(v,level+1)+';\n' for k,v in value.items())+indent+'}'
    if isinstance(value,list): return '('+', '.join(serialize(v,level) for v in value)+')'
    if isinstance(value,int): return str(value)
    return json.dumps(value)
projectdir=ROOT/'TouchColorWatch.xcodeproj'; (projectdir/'xcshareddata/xcschemes').mkdir(parents=True,exist_ok=True)
(projectdir/'project.pbxproj').write_text('// !$*UTF8*$!\n'+serialize(dict(archiveVersion=1,classes={},objectVersion=56,objects=objects,rootObject=uid('Project')))+'\n')
scheme=ET.Element('Scheme',LastUpgradeVersion='2700',version='1.3')
action=ET.SubElement(scheme,'BuildAction',parallelizeBuildables='YES',buildImplicitDependencies='YES')
entries=ET.SubElement(action,'BuildActionEntries')
def reference(parent,name): ET.SubElement(parent,'BuildableReference',BuildableIdentifier='primary',BlueprintIdentifier=uid(name),BuildableName='TouchColor.app' if name=='TouchColorWatch' else name+'.xctest',BlueprintName=name,ReferencedContainer='container:TouchColorWatch.xcodeproj')
entry=ET.SubElement(entries,'BuildActionEntry',buildForTesting='YES',buildForRunning='YES',buildForProfiling='YES',buildForArchiving='YES',buildForAnalyzing='YES'); reference(entry,'TouchColorWatch')
action=ET.SubElement(scheme,'TestAction',buildConfiguration='Debug',selectedDebuggerIdentifier='Xcode.DebuggerFoundation.Debugger.LLDB',selectedLauncherIdentifier='Xcode.IDEFoundation.Launcher.LLDB',shouldUseLaunchSchemeArgsEnv='YES')
testables=ET.SubElement(action,'Testables')
for name in ['TouchColorWatchTests','TouchColorWatchUITests']: reference(ET.SubElement(testables,'TestableReference',skipped='NO',parallelizable='NO'),name)
launch=ET.SubElement(scheme,'LaunchAction',buildConfiguration='Debug',selectedDebuggerIdentifier='Xcode.DebuggerFoundation.Debugger.LLDB',selectedLauncherIdentifier='Xcode.IDEFoundation.Launcher.LLDB',launchStyle='0',useCustomWorkingDirectory='NO',ignoresPersistentStateOnLaunch='NO',debugDocumentVersioning='YES',debugServiceExtension='internal',allowLocationSimulation='NO')
reference(ET.SubElement(launch,'BuildableProductRunnable',runnableDebuggingMode='0'),'TouchColorWatch')
ET.SubElement(scheme,'AnalyzeAction',buildConfiguration='Debug'); ET.SubElement(scheme,'ArchiveAction',buildConfiguration='Release',revealArchiveInOrganizer='YES')
ET.indent(scheme); ET.ElementTree(scheme).write(projectdir/'xcshareddata/xcschemes/TouchColorWatch.xcscheme',encoding='UTF-8',xml_declaration=True)
