#!/usr/bin/env python3
"""Independent simulator-only fixture host, never a TouchColor target dependency."""
from pathlib import Path
import hashlib
import json
import plistlib
import xml.etree.ElementTree as ET

root=Path(__file__).resolve().parents[1]/'TestFixtures'
project=root/'PaletteFixtures.xcodeproj'
objects={}
def uid(name): return hashlib.sha1(('fixture:'+name).encode()).hexdigest()[:24].upper()
def add(key,isa,**fields):
    identifier=uid(key);objects[identifier]=dict(isa=isa,**fields);return identifier
source=add('source','PBXFileReference',lastKnownFileType='sourcecode.c.objc',path='PaletteFixtures/main.m',sourceTree='<group>')
info=add('info','PBXFileReference',lastKnownFileType='text.plist.xml',path='PaletteFixtures/Info.plist',sourceTree='<group>')
product=add('product','PBXFileReference',explicitFileType='wrapper.application',path='PaletteFixtures.app',sourceTree='BUILT_PRODUCTS_DIR',includeInIndex=0)
build=add('build','PBXBuildFile',fileRef=source)
phases=[add('sources','PBXSourcesBuildPhase',buildActionMask=2147483647,files=[build],runOnlyForDeploymentPostprocessing=0),add('frameworks','PBXFrameworksBuildPhase',buildActionMask=2147483647,files=[],runOnlyForDeploymentPostprocessing=0),add('resources','PBXResourcesBuildPhase',buildActionMask=2147483647,files=[],runOnlyForDeploymentPostprocessing=0)]
def configs(name,settings):
    config=add(name+'Debug','XCBuildConfiguration',name='Debug',buildSettings=settings)
    return add(name+'configs','XCConfigurationList',buildConfigurations=[config],defaultConfigurationIsVisible=0,defaultConfigurationName='Debug')
target=add('target','PBXNativeTarget',name='PaletteFixtures',productName='PaletteFixtures',productReference=product,productType='com.apple.product-type.application',buildPhases=phases,buildRules=[],dependencies=[],buildConfigurationList=configs('target',dict(PRODUCT_NAME='PaletteFixtures',PRODUCT_BUNDLE_IDENTIFIER='com.mango.touchColor.tests.paletteFixtures',INFOPLIST_FILE='PaletteFixtures/Info.plist',CODE_SIGNING_ALLOWED='NO',SKIP_INSTALL='YES')))
products=add('products','PBXGroup',children=[product],name='Products',sourceTree='<group>')
group=add('group','PBXGroup',children=[source,info,products],sourceTree='<group>')
settings=dict(CLANG_ENABLE_MODULES='YES',CLANG_ENABLE_OBJC_ARC='YES',GCC_PREPROCESSOR_DEFINITIONS=['DEBUG=1','$(inherited)'],IPHONEOS_DEPLOYMENT_TARGET='15.0',SDKROOT='iphonesimulator',SUPPORTED_PLATFORMS='iphonesimulator',TARGETED_DEVICE_FAMILY='1,2',SUPPORTS_MACCATALYST='NO')
root_id=add('project','PBXProject',attributes=dict(LastUpgradeCheck='2700'),buildConfigurationList=configs('project',settings),compatibilityVersion='Xcode 14.0',developmentRegion='en',knownRegions=['en'],hasScannedForEncodings=0,mainGroup=group,productRefGroup=products,projectDirPath='',projectRoot='',targets=[target])
def serialize(value,level=0):
    indent='\t'*level
    if isinstance(value,dict): return '{\n'+''.join(indent+'\t'+json.dumps(str(k))+' = '+serialize(v,level+1)+';\n' for k,v in value.items())+indent+'}'
    if isinstance(value,list): return '('+', '.join(serialize(v,level) for v in value)+')'
    return str(value) if isinstance(value,int) else json.dumps(value)
project.mkdir(parents=True,exist_ok=True)
(project/'project.pbxproj').write_text('// !$*UTF8*$!\n'+serialize(dict(archiveVersion=1,classes={},objectVersion=56,objects=objects,rootObject=root_id))+'\n')
metadata=dict(CFBundleDisplayName='Palette Fixtures',CFBundleName='PaletteFixtures',CFBundleIdentifier='$(PRODUCT_BUNDLE_IDENTIFIER)',CFBundleExecutable='$(EXECUTABLE_NAME)',CFBundlePackageType='APPL',CFBundleShortVersionString='1.0',CFBundleVersion='1',LSRequiresIPhoneOS=True,UIFileSharingEnabled=True,LSSupportsOpeningDocumentsInPlace=True,UILaunchScreen={},UISupportedInterfaceOrientations=['UIInterfaceOrientationPortrait','UIInterfaceOrientationLandscapeLeft','UIInterfaceOrientationLandscapeRight'],UIApplicationSceneManifest={'UIApplicationSupportsMultipleScenes':False,'UISceneConfigurations':{'UIWindowSceneSessionRoleApplication':[{'UISceneConfigurationName':'Fixture','UISceneDelegateClassName':'PaletteFixtureDelegate'}]}})
(root/'PaletteFixtures/Info.plist').write_bytes(plistlib.dumps(metadata,sort_keys=True))
scheme=ET.Element('Scheme',LastUpgradeVersion='2700',version='1.3')
action=ET.SubElement(scheme,'BuildAction',parallelizeBuildables='NO',buildImplicitDependencies='NO')
entry=ET.SubElement(ET.SubElement(action,'BuildActionEntries'),'BuildActionEntry',buildForTesting='YES',buildForRunning='YES',buildForProfiling='NO',buildForArchiving='NO',buildForAnalyzing='NO')
ET.SubElement(entry,'BuildableReference',BuildableIdentifier='primary',BlueprintIdentifier=target,BuildableName='PaletteFixtures.app',BlueprintName='PaletteFixtures',ReferencedContainer='container:PaletteFixtures.xcodeproj')
ET.indent(scheme)
directory=project/'xcshareddata/xcschemes';directory.mkdir(parents=True,exist_ok=True)
ET.ElementTree(scheme).write(directory/'PaletteFixtures.xcscheme',encoding='UTF-8',xml_declaration=True)
assert 'PaletteFixtures' not in (root.parent/'TouchColor.xcodeproj/project.pbxproj').read_text()
