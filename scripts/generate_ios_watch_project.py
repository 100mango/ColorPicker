#!/usr/bin/env python3
"""Explicit, deterministic iOS+Watch package projection of qualified c664.

Never rewrites the original iOS or Watch project/source. The three generated
Objective-C inputs restore only historical launch and inbox entry deltas.
"""
from pathlib import Path
import copy, hashlib, json
import xml.etree.ElementTree as ET
from verify_original_ios_package import generated_project

ROOT=Path(__file__).resolve().parents[1]
PROJECT='TouchColor-iOS-Watch.xcodeproj'
INTEGRATION='TouchColorPhoneCompanion/Integration'
BASE_HASHES={'ColorAppDelegate.m': '17bdef036d12826db783e7c9df64a6a389532f994100fd9070d9cc47eba4b554', 'ColorMainViewController.m': '7b49b341c020126ee8c58be3a5ce77ad1ae11411224deb1e35bf23f2b0770dc4', 'TCWorkspaceViewController.m': '62984c4e0f0589d724a76e62ab1b74f6459bbbaf7111572adad725c4168f7da8'}
OPERATIONS={'ColorAppDelegate.m': [['#import "ColorAppDelegate.h"', '#import "ColorAppDelegate.h"\n#import "TouchColor-Swift.h"', 1], ['    return YES;', '    [[TCWatchPaletteInbox sharedInbox] activate];\n    return YES;', 1]], 'ColorMainViewController.m': [['#import "ColorMainViewController.h"', '#import "ColorMainViewController.h"\n#import "TCWatchInboxIntegration.h"', 1], ['NSLocalizedString(@"Import Palette", nil)];', 'NSLocalizedString(@"Import Palette", nil), NSLocalizedString(@"Watch Inbox", nil)];', 1], ['@"palette.import.open"];', '@"palette.import.open", @"watch.inbox.open"];', 1], ['@"square.and.arrow.down"];', '@"square.and.arrow.down", @"applewatch"];', 2], ['- (void)showMessage:(NSString *)message {', '- (void)openWatchInbox {\n    UIViewController *presenter = [self sourcePresenter];\n    if (presenter.presentedViewController || self.loading.isAnimating) return;\n    [self sourceFlowActive:YES];\n    __weak typeof(self) weakSelf = self;\n    [[TCWatchPaletteInbox sharedInbox] presentInboxFrom:presenter completion:^{ [weakSelf sourceFlowActive:NO]; }];\n}\n- (void)showMessage:(NSString *)message {', 1], ['    else if (button.tag == 3) [self openPaletteImport];', '    else if (button.tag == 3) [self openPaletteImport];\n    else if (button.tag == 4) [self openWatchInbox];', 1]], 'TCWorkspaceViewController.m': [['#import "TCWorkspaceViewController.h"', '#import "TCWorkspaceViewController.h"\n#import "TCWatchInboxIntegration.h"', 1], ['    UIBarButtonItem *sources = [[UIBarButtonItem alloc] initWithImage:[UIImage systemImageNamed:@"plus"] menu:[UIMenu menuWithTitle:NSLocalizedString(@"Color Sources", nil) children:@[photo,camera,live,paletteImport,privacy]]];', '    UIAction *inbox = [UIAction actionWithTitle:NSLocalizedString(@"Watch Inbox", nil) image:[UIImage systemImageNamed:@"applewatch"] identifier:@"watch.inbox.open" handler:^(UIAction *action) { [weakSelf.palette openWatchInbox]; }];\n    UIBarButtonItem *sources = [[UIBarButtonItem alloc] initWithImage:[UIImage systemImageNamed:@"plus"] menu:[UIMenu menuWithTitle:NSLocalizedString(@"Color Sources", nil) children:@[photo,camera,live,paletteImport,inbox,privacy]]];', 1]]}
HEADER='#import "ColorMainViewController.h"\n\n// The original iOS header stays unchanged. Only the Watch-package projection\n// restores this existing action to its shipping implementation and workspace.\n@interface ColorMainViewController (TCWatchInboxIntegration)\n- (void)openWatchInbox;\n@end\n'

def need(ok,reason):
    if not ok:raise ValueError(reason)

def uid(key):return hashlib.sha1(key.encode()).hexdigest()[:24].upper()
def serialize(value,level=0):
    indent='\t'*level
    if isinstance(value,dict):return '{\n'+''.join(indent+'\t'+json.dumps(str(k))+' = '+serialize(v,level+1)+';\n' for k,v in value.items())+indent+'}'
    if isinstance(value,list):return '('+', '.join(serialize(v,level) for v in value)+')'
    if isinstance(value,int):return str(value)
    return json.dumps(value)

def projected_sources(root=ROOT):
    result={INTEGRATION+'/TCWatchInboxIntegration.h':HEADER}
    for name,operations in OPERATIONS.items():
        raw=(root/'ColorPicker'/name).read_bytes()
        need(hashlib.sha256(raw).hexdigest()==BASE_HASHES[name],'qualified original source changed: '+name)
        value=raw.decode()
        for old,new,count in operations:
            need(value.count(old)==count,'integration anchor changed: '+name)
            value=value.replace(old,new)
        result[INTEGRATION+'/'+name]=value
    return result

def projection(root=ROOT):
    project=generated_project((root/'TouchColor.xcodeproj/project.pbxproj').read_bytes())
    objects=project['objects'];app=objects[uid('TouchColor')]
    def add(key,isa,**fields):
        ident=uid(key);need(ident not in objects,'duplicate projection object: '+key)
        objects[ident]=dict(isa=isa,**fields);return ident
    main=objects[objects[project['rootObject']]['mainGroup']]
    # Replace references only in this new project. All other current iOS inputs
    # remain exactly the qualified originals, including import/lifecycle fixes.
    for name in OPERATIONS:
        objects[uid('file:ColorPicker/'+name)]['path']=INTEGRATION+'/'+name
    header=add('WatchInboxIntegrationHeader','PBXFileReference',lastKnownFileType='sourcecode.c.h',path=INTEGRATION+'/TCWatchInboxIntegration.h',sourceTree='<group>')
    main['children'].append(header)
    source_phase=objects[next(p for p in app['buildPhases'] if objects[p]['isa']=='PBXSourcesBuildPhase')]
    for name in ('PhonePaletteInbox.swift','PhonePaletteInboxController.swift'):
        ref=add('file:TouchColorPhoneCompanion/'+name,'PBXFileReference',lastKnownFileType='sourcecode.swift',path='TouchColorPhoneCompanion/'+name,sourceTree='<group>')
        source_phase['files'].append(add('build:'+ref,'PBXBuildFile',fileRef=ref));main['children'].append(ref)
    watch=add('file:TouchColorWatch.xcodeproj','PBXFileReference',lastKnownFileType='wrapper.pb-project',path='TouchColorWatch.xcodeproj',sourceTree='<group>')
    wuid=lambda key:hashlib.sha1(('watch:'+key).encode()).hexdigest()[:24].upper()
    proxy=add('WatchProductProxy','PBXContainerItemProxy',containerPortal=watch,proxyType=2,remoteGlobalIDString=wuid('TouchColorWatchproduct'),remoteInfo='TouchColorWatch')
    product=add('WatchProductReference','PBXReferenceProxy',fileType='wrapper.application',path='TouchColor.app',remoteRef=proxy,sourceTree='BUILT_PRODUCTS_DIR')
    products=add('WatchProducts','PBXGroup',children=[product],name='Products',sourceTree='<group>')
    target=add('WatchTargetProxy','PBXContainerItemProxy',containerPortal=watch,proxyType=1,remoteGlobalIDString=wuid('TouchColorWatch'),remoteInfo='TouchColorWatch')
    dependency=add('WatchTargetDependency','PBXTargetDependency',name='TouchColorWatch',targetProxy=target,platformFilter='ios')
    build=add('EmbedWatchBuildFile','PBXBuildFile',fileRef=product,platformFilter='ios',settings=dict(ATTRIBUTES=['RemoveHeadersOnCopy']))
    embed=add('EmbedWatchContent','PBXCopyFilesBuildPhase',buildActionMask=2147483647,files=[build],dstPath='$(CONTENTS_FOLDER_PATH)/Watch',dstSubfolderSpec=16,name='Embed Watch Content',runOnlyForDeploymentPostprocessing=0)
    app['dependencies']=[dependency];app['buildPhases'].append(embed);main['children'].append(watch)
    objects[project['rootObject']]['projectReferences']=[dict(ProjectRef=watch,ProductGroup=products)]
    for config in objects[app['buildConfigurationList']]['buildConfigurations']:
        # Both products are TouchColor.app. Give the phone symbols a unique
        # archive name; the Watch product, executable and graph are unchanged.
        objects[config]['buildSettings']['DWARF_DSYM_FILE_NAME']='TouchColor-iOS.app.dSYM'
        objects[config]['buildSettings']['HEADER_SEARCH_PATHS'].append('$(SRCROOT)/'+INTEGRATION)
    return project

def generate(root=ROOT):
    target=root/PROJECT;(target/'xcshareddata/xcschemes').mkdir(parents=True,exist_ok=True)
    for path,value in projected_sources(root).items():
        p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
    (target/'project.pbxproj').write_text('// !$*UTF8*$!\n'+serialize(projection(root))+'\n')
    scheme=ET.parse(root/'TouchColor.xcodeproj/xcshareddata/xcschemes/TouchColor.xcscheme')
    for element in scheme.iter('BuildableReference'):element.set('ReferencedContainer','container:'+PROJECT)
    ET.indent(scheme);scheme.write(target/'xcshareddata/xcschemes/TouchColor.xcscheme',encoding='UTF-8',xml_declaration=True)
    workspace=target/'project.xcworkspace';workspace.mkdir(exist_ok=True)
    (workspace/'contents.xcworkspacedata').write_text('<?xml version="1.0" encoding="UTF-8"?>\n<Workspace version="1.0"><FileRef location="self:"/></Workspace>\n')

if __name__=='__main__':generate()
