#!/usr/bin/env python3
"""Generate only the independent DEBUG static Watch Crown control project."""
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
APP = 'TouchColorWatchCrownControl'
UI = 'TouchColorWatchCrownControlUITests'


def generate(root=ROOT):
    objects = {}

    def uid(key):
        return hashlib.sha1(('watch-static-crown-control:' + key).encode()).hexdigest()[:24].upper()

    def add(key, isa, **fields):
        identifier = uid(key)
        objects[identifier] = dict(isa=isa, **fields)
        return identifier

    def ref(path, kind):
        return add('file:' + path, 'PBXFileReference', lastKnownFileType=kind, path=path, sourceTree='<group>')

    def phase(name, kind, files=()):
        return add(name, kind, buildActionMask=2147483647,
                   files=[add(name + ':' + item, 'PBXBuildFile', fileRef=item) for item in files],
                   runOnlyForDeploymentPostprocessing=0)

    def configs(name, settings):
        # No Release config or archive action is provided; Swift also rejects !DEBUG.
        values = dict(settings, SWIFT_ACTIVE_COMPILATION_CONDITIONS='DEBUG', ENABLE_TESTABILITY='YES',
                      ONLY_ACTIVE_ARCH='YES', SWIFT_OPTIMIZATION_LEVEL='-Onone', DEBUG_INFORMATION_FORMAT='dwarf')
        debug = add(name + 'Debug', 'XCBuildConfiguration', name='Debug', buildSettings=values)
        return add(name + 'configs', 'XCConfigurationList', buildConfigurations=[debug],
                   defaultConfigurationIsVisible=0, defaultConfigurationName='Debug')

    # Explicit allowlist, never directory discovery or reuse of the product generator.
    app_sources = [ref(APP + '/StaticCrownControlApp.swift', 'sourcecode.swift')]
    ui_sources = [ref(UI + '/WatchStaticCrownControlTests.swift', 'sourcecode.swift')]
    header = ref(UI + '/TCStaticListGeometry.h', 'sourcecode.c.h')
    products, targets = [], []
    for name, is_app, source_files in [(APP, True, app_sources), (UI, False, ui_sources)]:
        product = add(name + 'product', 'PBXFileReference',
                      explicitFileType='wrapper.application' if is_app else 'wrapper.cfbundle', includeInIndex=0,
                      path=name + ('.app' if is_app else '.xctest'), sourceTree='BUILT_PRODUCTS_DIR')
        products.append(product)
        settings = dict(PRODUCT_NAME='$(TARGET_NAME)', PRODUCT_MODULE_NAME=name,
                        PRODUCT_BUNDLE_IDENTIFIER='com.mango.touchColor.watchCrownControl' + ('' if is_app else '.uitests'),
                        GENERATE_INFOPLIST_FILE='YES', WATCHOS_DEPLOYMENT_TARGET='10.0', SDKROOT='watchos',
                        SUPPORTED_PLATFORMS='watchos watchsimulator', TARGETED_DEVICE_FAMILY='4',
                        SUPPORTS_MACCATALYST='NO', SWIFT_VERSION='5.0', CLANG_ENABLE_MODULES='YES',
                        CODE_SIGN_STYLE='Automatic', CODE_SIGNING_ALLOWED='NO', SKIP_INSTALL='YES',
                        LD_RUNPATH_SEARCH_PATHS=['$(inherited)', '@executable_path/Frameworks', '@loader_path/Frameworks'])
        dependencies = []
        if is_app:
            settings.update(INFOPLIST_KEY_CFBundleDisplayName='Crown Control', INFOPLIST_KEY_WKApplication='YES',
                            INFOPLIST_KEY_WKWatchOnly='YES',
                            MARKETING_VERSION='1.0', CURRENT_PROJECT_VERSION='1')
        else:
            settings.update(TEST_TARGET_NAME=APP, SWIFT_OBJC_BRIDGING_HEADER=UI + '/TCStaticListGeometry.h')
            proxy = add(name + 'proxy', 'PBXContainerItemProxy', containerPortal=uid('Project'), proxyType=1,
                        remoteGlobalIDString=uid(APP), remoteInfo=APP)
            dependencies = [add(name + 'dependency', 'PBXTargetDependency', target=uid(APP), targetProxy=proxy)]
        targets.append(add(name, 'PBXNativeTarget', buildConfigurationList=configs(name, settings),
                           buildPhases=[phase(name + 'sources', 'PBXSourcesBuildPhase', source_files),
                                        phase(name + 'frameworks', 'PBXFrameworksBuildPhase'),
                                        phase(name + 'resources', 'PBXResourcesBuildPhase')],
                           buildRules=[], dependencies=dependencies, name=name, productName=name,
                           productReference=product,
                           productType='com.apple.product-type.' + ('application' if is_app else 'bundle.ui-testing')))
    product_group = add('Products', 'PBXGroup', children=products, name='Products', sourceTree='<group>')
    group = add('MainGroup', 'PBXGroup', children=app_sources + ui_sources + [header, product_group], sourceTree='<group>')
    add('Project', 'PBXProject', attributes=dict(LastUpgradeCheck='2700', TargetAttributes={uid(UI): dict(TestTargetID=uid(APP))}),
        buildConfigurationList=configs('Project', dict(SWIFT_VERSION='5.0', WATCHOS_DEPLOYMENT_TARGET='10.0',
            SDKROOT='watchos', CLANG_ENABLE_MODULES='YES', CLANG_ENABLE_OBJC_ARC='YES',
            GCC_C_LANGUAGE_STANDARD='gnu17', ENABLE_USER_SCRIPT_SANDBOXING='YES')),
        compatibilityVersion='Xcode 14.0', developmentRegion='en', hasScannedForEncodings=0,
        knownRegions=['en', 'Base'], mainGroup=group, productRefGroup=product_group,
        projectDirPath='', projectRoot='', targets=targets)

    def serialize(value, level=0):
        indent = '\t' * level
        if isinstance(value, dict):
            return '{\n' + ''.join(indent + '\t' + json.dumps(str(key)) + ' = ' + serialize(item, level + 1) + ';\n'
                                 for key, item in value.items()) + indent + '}'
        if isinstance(value, list):
            return '(' + ', '.join(serialize(item, level) for item in value) + ')'
        return str(value) if isinstance(value, int) else json.dumps(value)

    project = root / (APP + '.xcodeproj')
    schemes = project / 'xcshareddata/xcschemes'
    schemes.mkdir(parents=True, exist_ok=True)
    (project / 'project.pbxproj').write_text('// !$*UTF8*$!\n' + serialize(dict(archiveVersion=1, classes={},
         objectVersion=56, objects=objects, rootObject=uid('Project'))) + '\n')
    scheme = ET.Element('Scheme', LastUpgradeVersion='2700', version='1.3')
    build = ET.SubElement(scheme, 'BuildAction', parallelizeBuildables='NO', buildImplicitDependencies='YES')
    entries = ET.SubElement(build, 'BuildActionEntries')

    def reference(parent, name):
        ET.SubElement(parent, 'BuildableReference', BuildableIdentifier='primary', BlueprintIdentifier=uid(name),
                      BuildableName=name + ('.app' if name == APP else '.xctest'), BlueprintName=name,
                      ReferencedContainer='container:' + APP + '.xcodeproj')

    for name in [APP, UI]:
        entry = ET.SubElement(entries, 'BuildActionEntry', buildForTesting='YES', buildForRunning='YES' if name == APP else 'NO',
                              buildForProfiling='NO', buildForArchiving='NO', buildForAnalyzing='YES')
        reference(entry, name)
    test = ET.SubElement(scheme, 'TestAction', buildConfiguration='Debug',
                        selectedDebuggerIdentifier='Xcode.DebuggerFoundation.Debugger.LLDB',
                        selectedLauncherIdentifier='Xcode.IDEFoundation.Launcher.LLDB', shouldUseLaunchSchemeArgsEnv='YES')
    testables = ET.SubElement(test, 'Testables')
    reference(ET.SubElement(testables, 'TestableReference', skipped='NO', parallelizable='NO'), UI)
    launch = ET.SubElement(scheme, 'LaunchAction', buildConfiguration='Debug',
                          selectedDebuggerIdentifier='Xcode.DebuggerFoundation.Debugger.LLDB',
                          selectedLauncherIdentifier='Xcode.IDEFoundation.Launcher.LLDB', launchStyle='0',
                          useCustomWorkingDirectory='NO', ignoresPersistentStateOnLaunch='YES',
                          debugDocumentVersioning='YES', debugServiceExtension='internal', allowLocationSimulation='NO')
    reference(ET.SubElement(launch, 'BuildableProductRunnable', runnableDebuggingMode='0'), APP)
    ET.SubElement(scheme, 'AnalyzeAction', buildConfiguration='Debug')
    ET.indent(scheme)
    ET.ElementTree(scheme).write(schemes / (APP + '.xcscheme'), encoding='UTF-8', xml_declaration=True)
    return objects


if __name__ == '__main__':
    generate()
