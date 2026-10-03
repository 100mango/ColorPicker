#!/usr/bin/env python3
"""Generate a deterministic, dependency-free Xcode project (Python standard library only)."""
from pathlib import Path
import hashlib
import json
import plistlib
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
objects = {}
def uid(key): return hashlib.sha1(key.encode()).hexdigest()[:24].upper()
def add(key, isa, **fields):
    key = uid(key)
    objects[key] = dict(isa=isa, **fields)
    return key
def ref(path, kind): return add('file:'+path, 'PBXFileReference', lastKnownFileType=kind, path=path, sourceTree='<group>')
def filetype(path): return 'sourcecode.c.objc' if path.endswith('.m') else 'sourcecode.c.h'
def build(refid): return add('build:'+refid, 'PBXBuildFile', fileRef=refid)
def phase(name, isa, refs): return add(name, isa, buildActionMask=2147483647, files=[build(r) for r in refs], runOnlyForDeploymentPostprocessing=0)
def configlist(name, settings):
    configs=[]
    for configuration in ('Debug', 'Release'):
        values=dict(settings)
        if name=='Project':
            values.update(GCC_OPTIMIZATION_LEVEL='0' if configuration=='Debug' else 's', GCC_PREPROCESSOR_DEFINITIONS=['$(inherited)', 'DEBUG=1'] if configuration=='Debug' else ['$(inherited)'], ENABLE_TESTABILITY='YES' if configuration=='Debug' else 'NO', DEBUG_INFORMATION_FORMAT='dwarf' if configuration=='Debug' else 'dwarf-with-dsym')
        configs.append(add(name+configuration,'XCBuildConfiguration',name=configuration,buildSettings=values))
    return add(name+'configs','XCConfigurationList', buildConfigurations=configs, defaultConfigurationIsVisible=0,defaultConfigurationName='Release')

sources=['main.m','ColorAppDelegate.m','ColorSceneDelegate.m','ColorMainViewController.m','ColorViewController.m','ColorRealTimeViewController.m','ColorDetectView.m','TCColorUtilities.m','TCPrivacyViewController.m','TCWorkspaceViewController.m']
headers=[p.replace('.m','.h') for p in sources if p!='main.m']
apprefs=[ref('ColorPicker/'+p,filetype(p)) for p in sources+headers]
resources=[ref('ColorPicker/Images.xcassets','folder.assetcatalog'),ref('ColorPicker/PrivacyInfo.xcprivacy','text.xml')]
for filename in ['Localizable.strings','InfoPlist.strings']:
    children=[add('loc:'+lang+filename, 'PBXFileReference', lastKnownFileType='text.plist.strings', name=lang, path='ColorPicker/'+lang+'.lproj/'+filename, sourceTree='<group>') for lang in ['en','zh-Hans']]
    resources.append(add('variant:'+filename,'PBXVariantGroup',children=children,name=filename,sourceTree='<group>'))
testrefs=[ref('ColorPickerTests/'+name,'sourcecode.c.objc') for name in ['ColorPickerTests.m','TCAdaptiveLayoutTests.m','TCWorkspaceTests.m']]
uirefs=[ref('TouchColorUITests/'+name,'sourcecode.c.objc') for name in ['TouchColorUITests.m','TouchColorIPadUITests.m']]
products=[]
projectid=uid('Project')
appTarget=uid('TouchColor')
targets=[]
for name,kind,refs in [('TouchColor','application',apprefs[:len(sources)]),('TouchColorTests','bundle.unit-test',testrefs),('TouchColorUITests','bundle.ui-testing',uirefs)]:
    isapp=name=='TouchColor'
    product=add(name+'product','PBXFileReference', explicitFileType='wrapper.application' if isapp else 'wrapper.cfbundle', includeInIndex=0,path=name+('.app' if isapp else '.xctest'),sourceTree='BUILT_PRODUCTS_DIR')
    products.append(product)
    phases=[phase(name+'sources','PBXSourcesBuildPhase',refs),phase(name+'frameworks','PBXFrameworksBuildPhase',[]),phase(name+'resources','PBXResourcesBuildPhase',resources if isapp else [])]
    settings=dict(PRODUCT_NAME='$(TARGET_NAME)', PRODUCT_BUNDLE_IDENTIFIER='com.mango.touchColor' if isapp else 'com.mango.touchColor.'+name, CODE_SIGN_STYLE='Automatic', HEADER_SEARCH_PATHS=['$(inherited)','$(SRCROOT)/ColorPicker'], LD_RUNPATH_SEARCH_PATHS=['$(inherited)','@executable_path/Frameworks','@loader_path/Frameworks'])
    if isapp: settings.update(INFOPLIST_FILE='ColorPicker/TouchColor-Info.plist', ASSETCATALOG_COMPILER_APPICON_NAME='AppIcon', MARKETING_VERSION='2.0', CURRENT_PROJECT_VERSION='20001')
    else: settings.update(GENERATE_INFOPLIST_FILE='YES', IPHONEOS_DEPLOYMENT_TARGET='17.0')
    if kind=='bundle.unit-test': settings.update(TEST_HOST='$(BUILT_PRODUCTS_DIR)/TouchColor.app/TouchColor', BUNDLE_LOADER='$(TEST_HOST)')
    if kind=='bundle.ui-testing': settings.update(TEST_TARGET_NAME='TouchColor')
    dependencies=[]
    if not isapp:
        proxy=add(name+'proxy','PBXContainerItemProxy',containerPortal=projectid,proxyType=1,remoteGlobalIDString=appTarget,remoteInfo='TouchColor')
        dependencies=[add(name+'dependency','PBXTargetDependency',target=appTarget,targetProxy=proxy)]
    targets.append(add(name,'PBXNativeTarget',buildConfigurationList=configlist(name,settings),buildPhases=phases,buildRules=[],dependencies=dependencies,name=name,productName=name,productReference=product,productType='com.apple.product-type.'+kind))
productgroup=add('Products','PBXGroup',children=products,name='Products',sourceTree='<group>')
group=add('MainGroup','PBXGroup',children=apprefs+resources+testrefs+uirefs+[ref('ColorPicker/TouchColor-Info.plist','text.plist.xml'), productgroup],sourceTree='<group>')
settings=dict(ALWAYS_SEARCH_USER_PATHS='NO',CLANG_ENABLE_MODULES='YES',CLANG_ENABLE_OBJC_ARC='YES',CLANG_WARN_BOOL_CONVERSION='YES',CLANG_WARN_CONSTANT_CONVERSION='YES',CLANG_WARN_ENUM_CONVERSION='YES',CLANG_WARN_INT_CONVERSION='YES',CLANG_WARN_OBJC_ROOT_CLASS='YES_ERROR',GCC_C_LANGUAGE_STANDARD='gnu17',GCC_WARN_ABOUT_RETURN_TYPE='YES_ERROR',GCC_WARN_UNINITIALIZED_AUTOS='YES',GCC_WARN_UNUSED_VARIABLE='YES',IPHONEOS_DEPLOYMENT_TARGET='15.0',SDKROOT='iphoneos',TARGETED_DEVICE_FAMILY='1,2',SUPPORTED_PLATFORMS='iphoneos iphonesimulator',SUPPORTS_MACCATALYST='NO',ENABLE_USER_SCRIPT_SANDBOXING='YES')
add('Project','PBXProject',attributes=dict(LastUpgradeCheck='2700',TargetAttributes={targets[1]:dict(TestTargetID=appTarget),targets[2]:dict(TestTargetID=appTarget)}),buildConfigurationList=configlist('Project',settings),compatibilityVersion='Xcode 14.0',developmentRegion='en',hasScannedForEncodings=0,knownRegions=['en','zh-Hans','Base'],mainGroup=group,productRefGroup=productgroup,projectDirPath='',projectRoot='',targets=targets)
def serialize(value, level=0):
    indent='\t'*level
    if isinstance(value,dict): return '{\n'+''.join(indent+'\t'+json.dumps(str(k))+' = '+serialize(v,level+1)+';\n' for k,v in value.items())+indent+'}'
    if isinstance(value,list): return '('+', '.join(serialize(v,level) for v in value)+')'
    if isinstance(value,int): return str(value)
    return json.dumps(value)
project=dict(archiveVersion=1,classes={},objectVersion=56,objects=objects,rootObject=projectid)
(ROOT/'TouchColor.xcodeproj/project.pbxproj').write_text('// !$*UTF8*$!\n'+serialize(project)+'\n')
scheme=ET.Element('Scheme',LastUpgradeVersion='2700',version='1.3')
buildaction=ET.SubElement(scheme,'BuildAction',parallelizeBuildables='YES',buildImplicitDependencies='YES')
entries=ET.SubElement(buildaction,'BuildActionEntries')
def reference(parent,name): ET.SubElement(parent,'BuildableReference',BuildableIdentifier='primary',BlueprintIdentifier=uid(name),BuildableName=name+('.app' if name=='TouchColor' else '.xctest'),BlueprintName=name,ReferencedContainer='container:TouchColor.xcodeproj')
entry=ET.SubElement(entries,'BuildActionEntry',buildForTesting='YES',buildForRunning='YES',buildForProfiling='YES',buildForArchiving='YES',buildForAnalyzing='YES');reference(entry,'TouchColor')
testaction=ET.SubElement(scheme,'TestAction',buildConfiguration='Debug',selectedDebuggerIdentifier='Xcode.DebuggerFoundation.Debugger.LLDB',selectedLauncherIdentifier='Xcode.IDEFoundation.Launcher.LLDB',shouldUseLaunchSchemeArgsEnv='YES')
testables=ET.SubElement(testaction,'Testables')
for name in ['TouchColorTests','TouchColorUITests']:
    testable=ET.SubElement(testables,'TestableReference',skipped='NO',parallelizable='NO');reference(testable,name)
launch=ET.SubElement(scheme,'LaunchAction',buildConfiguration='Debug',selectedDebuggerIdentifier='Xcode.DebuggerFoundation.Debugger.LLDB',selectedLauncherIdentifier='Xcode.IDEFoundation.Launcher.LLDB',launchStyle='0',useCustomWorkingDirectory='NO',ignoresPersistentStateOnLaunch='NO',debugDocumentVersioning='YES',debugServiceExtension='internal',allowLocationSimulation='YES')
reference(ET.SubElement(launch,'BuildableProductRunnable',runnableDebuggingMode='0'),'TouchColor')
ET.SubElement(scheme,'AnalyzeAction',buildConfiguration='Debug');ET.SubElement(scheme,'ArchiveAction',buildConfiguration='Release',revealArchiveInOrganizer='YES')
ET.indent(scheme)
ET.ElementTree(scheme).write(ROOT/'TouchColor.xcodeproj/xcshareddata/xcschemes/TouchColor.xcscheme',encoding='UTF-8',xml_declaration=True)
