#import <XCTest/XCTest.h>
#import "ColorMainViewController.h"
#import "ColorViewController.h"
#import "TCColorUtilities.h"

@interface ColorMainViewController (ImportLifecycleTests)
- (void)loadPhotoFromProvider:(NSItemProvider *)provider;
- (void)sourceFlowActive:(BOOL)active;
- (void)showMessage:(NSString *)message;
@end
@interface ColorViewController (ImportLifecycleTests)
- (void)handelColor:(NSString *)hex;
@end

@interface TCControlledPhotoProvider : NSItemProvider
@property (atomic, copy) void (^delivery)(NSURL *, NSError *);
@property (nonatomic, strong) NSProgress *loadProgress;
@property (nonatomic, strong) XCTestExpectation *requested;
@end
@implementation TCControlledPhotoProvider
- (instancetype)init {
    if ((self=[super init])) {
        _loadProgress=[NSProgress progressWithTotalUnitCount:1];
        _requested=[[XCTestExpectation alloc] initWithDescription:@"Provider received the file request"];
    }
    return self;
}
- (NSArray<NSString *> *)registeredTypeIdentifiers { return @[@"public.png"]; }
- (NSProgress *)loadFileRepresentationForTypeIdentifier:(NSString *)identifier completionHandler:(void (^)(NSURL *, NSError *))completionHandler {
    self.delivery=completionHandler; [self.requested fulfill]; return self.loadProgress;
}
- (void)deliverURL:(NSURL *)URL error:(NSError *)error returned:(XCTestExpectation *)returned {
    void (^callback)(NSURL *, NSError *)=self.delivery;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0), ^{
        if (callback) callback(URL,error);
        [returned fulfill];
    });
}
@end

@interface TCImportWorkspace : NSObject <TCColorWorkspaceDelegate>
@property (nonatomic, strong) UIViewController *canvas;
@property (nonatomic, strong) NSMutableArray<NSNumber *> *flowStates;
@property (nonatomic) BOOL loading;
@end
@implementation TCImportWorkspace
- (instancetype)init { if ((self=[super init])) _flowStates=[NSMutableArray new]; return self; }
- (UIViewController *)sourcePresenterForPalette:(ColorMainViewController *)palette { return palette; }
- (UIBarButtonItem *)sourceAnchorForPalette:(ColorMainViewController *)palette { return nil; }
- (void)palette:(ColorMainViewController *)palette showCanvas:(UIViewController *)canvas { self.canvas=canvas; }
- (void)palette:(ColorMainViewController *)palette sourceFlowActive:(BOOL)active { [self.flowStates addObject:@(active)]; }
- (void)palette:(ColorMainViewController *)palette loadingPhoto:(BOOL)loading { self.loading=loading; }
- (void)palette:(ColorMainViewController *)palette previewSavedColor:(NSString *)hex {}
@end

@interface TCImportPaletteSpy : ColorMainViewController
@property (nonatomic, strong) NSMutableArray<NSString *> *messages;
@end
@implementation TCImportPaletteSpy
- (instancetype)init { if ((self=[super init])) _messages=[NSMutableArray new]; return self; }
- (void)showMessage:(NSString *)message {
    [self.messages addObject:message];
    [self sourceFlowActive:YES]; // Same suspension boundary as the production native alert.
}
@end

// Locate the same real cancellation action independently of whether the
// original design presents it in its loading panel or a navigation bar.
static UIButton *TCVisibleImportCancel(UIView *root) {
    if ([root isKindOfClass:UIButton.class] && [root.accessibilityIdentifier isEqualToString:@"photo.import.cancel"]) {
        for (UIView *ancestor=root;ancestor;ancestor=ancestor.superview) {
            if (ancestor.hidden || ancestor.alpha<=0 || !ancestor.userInteractionEnabled) return nil;
        }
        return (UIButton *)root;
    }
    for (UIView *child in root.subviews) {
        UIButton *found=TCVisibleImportCancel(child);
        if (found) return found;
    }
    return nil;
}

@interface TCPhotoImportLifecycleTests : XCTestCase
@end
@implementation TCPhotoImportLifecycleTests
- (NSURL *)imageFileWithColor:(UIColor *)color {
    UIGraphicsImageRendererFormat *format=[UIGraphicsImageRendererFormat defaultFormat];
    format.scale=1;format.preferredRange=UIGraphicsImageRendererFormatRangeStandard;
    UIImage *image=[[[UIGraphicsImageRenderer alloc] initWithSize:CGSizeMake(3,2) format:format] imageWithActions:^(UIGraphicsImageRendererContext *context) {
        [color setFill];[context fillRect:CGRectMake(0,0,3,2)];
    }];
    NSURL *URL=[NSURL fileURLWithPath:[NSTemporaryDirectory() stringByAppendingPathComponent:[NSUUID.UUID.UUIDString stringByAppendingString:@".png"]]];
    XCTAssertTrue([UIImagePNGRepresentation(image) writeToURL:URL atomically:YES]);
    return URL;
}
- (TCImportPaletteSpy *)paletteWithWorkspace:(TCImportWorkspace *)workspace original:(ColorViewController *)original {
    workspace.canvas=original;
    [original handelColor:@"#123456"];
    TCImportPaletteSpy *palette=[TCImportPaletteSpy new];palette.workspaceDelegate=workspace;
    [palette loadViewIfNeeded];return palette;
}
- (void)waitForCondition:(BOOL (^)(void))condition description:(NSString *)description {
    XCTNSPredicateExpectation *ready=[[XCTNSPredicateExpectation alloc] initWithPredicate:[NSPredicate predicateWithBlock:^BOOL(id object,NSDictionary *bindings) { return condition(); }] object:nil];
    XCTAssertEqual([XCTWaiter waitForExpectations:@[ready] timeout:10],XCTWaiterResultCompleted,@"%@",description);
}
- (void)testProviderFailureKeepsCanvasPaletteAndLiveSuspension {
    TCImportWorkspace *workspace=[TCImportWorkspace new];ColorViewController *original=[ColorViewController new];
    TCImportPaletteSpy *palette=[self paletteWithWorkspace:workspace original:original];
    id history=[NSUserDefaults.standardUserDefaults objectForKey:@"colorArray"];
    id backup=[NSUserDefaults.standardUserDefaults objectForKey:@"colorArrayRecoveryBackup"];
    TCControlledPhotoProvider *provider=[TCControlledPhotoProvider new];
    [palette loadPhotoFromProvider:provider];
    XCTAssertEqual([XCTWaiter waitForExpectations:@[provider.requested] timeout:5],XCTWaiterResultCompleted);
    XCTAssertTrue(workspace.loading);
    UIButton *cancel=TCVisibleImportCancel(palette.view);
    XCTAssertNotNil(cancel,@"The real loading Cancel action must remain visible and reachable in the restored design");
    XCTAssertTrue(cancel.enabled);
    XCTestExpectation *returned=[self expectationWithDescription:@"Failed provider returned"];
    [provider deliverURL:nil error:[NSError errorWithDomain:@"TouchColor.ProviderFixture" code:1 userInfo:nil] returned:returned];
    [self waitForExpectations:@[returned] timeout:5];
    [self waitForCondition:^BOOL { return palette.messages.count==1; } description:@"Native error is exposed"];
    XCTAssertEqual(workspace.canvas,original);
    XCTAssertEqualObjects([original valueForKey:@"selectedHex"],@"#123456");
    XCTAssertFalse(workspace.loading);
    XCTAssertFalse([workspace.flowStates containsObject:@NO],@"Live capture stays suspended until the error alert closes");
    XCTAssertEqualObjects([NSUserDefaults.standardUserDefaults objectForKey:@"colorArray"],history);
    XCTAssertEqualObjects([NSUserDefaults.standardUserDefaults objectForKey:@"colorArrayRecoveryBackup"],backup);
}
- (void)testCancelledProviderCannotReplaceANewerPhoto {
    TCImportWorkspace *workspace=[TCImportWorkspace new];ColorViewController *original=[ColorViewController new];
    TCImportPaletteSpy *palette=[self paletteWithWorkspace:workspace original:original];
    TCControlledPhotoProvider *old=[TCControlledPhotoProvider new], *new=[TCControlledPhotoProvider new];
    NSURL *red=[self imageFileWithColor:UIColor.redColor], *blue=[self imageFileWithColor:UIColor.blueColor];
    @try {
        [palette loadPhotoFromProvider:old];
        XCTAssertEqual([XCTWaiter waitForExpectations:@[old.requested] timeout:5],XCTWaiterResultCompleted);
        [palette cancelPhotoImport];
        [self waitForCondition:^BOOL { return old.loadProgress.cancelled; } description:@"Old provider progress is cancelled after registration"];XCTAssertFalse(workspace.loading);
        XCTAssertEqualObjects(workspace.flowStates.lastObject,@NO);XCTAssertEqual(workspace.canvas,original);
        [palette loadPhotoFromProvider:new];
        XCTAssertEqual([XCTWaiter waitForExpectations:@[new.requested] timeout:5],XCTWaiterResultCompleted);
        XCTestExpectation *fresh=[self expectationWithDescription:@"New file returned"];
        [new deliverURL:blue error:nil returned:fresh];[self waitForExpectations:@[fresh] timeout:5];
        [self waitForCondition:^BOOL { return workspace.canvas!=original; } description:@"New photo becomes current"];
        UIViewController *selected=workspace.canvas;
        XCTAssertEqualObjects(TCSampleImage([selected valueForKey:@"image"],CGPointMake(0.5,0.5)),@"#0000ff");
        XCTestExpectation *late=[self expectationWithDescription:@"Old cancelled file returned"];
        [old deliverURL:red error:nil returned:late];[self waitForExpectations:@[late] timeout:5];
        XCTAssertEqual(workspace.canvas,selected);XCTAssertEqual(palette.messages.count,0u);
        XCTAssertFalse(workspace.loading);XCTAssertEqualObjects(workspace.flowStates.lastObject,@NO);
    } @finally {
        [NSFileManager.defaultManager removeItemAtURL:red error:nil];
        [NSFileManager.defaultManager removeItemAtURL:blue error:nil];
    }
}
- (void)testAnOldCompletionCannotClearANewerLoadingState {
    TCImportWorkspace *workspace=[TCImportWorkspace new];ColorViewController *original=[ColorViewController new];
    TCImportPaletteSpy *palette=[self paletteWithWorkspace:workspace original:original];
    TCControlledPhotoProvider *old=[TCControlledPhotoProvider new], *new=[TCControlledPhotoProvider new];
    [palette loadPhotoFromProvider:old];
    XCTAssertEqual([XCTWaiter waitForExpectations:@[old.requested] timeout:5],XCTWaiterResultCompleted);
    [palette loadPhotoFromProvider:new];
    XCTAssertEqual([XCTWaiter waitForExpectations:@[new.requested] timeout:5],XCTWaiterResultCompleted);
    XCTestExpectation *late=[self expectationWithDescription:@"Old error delivered during a new load"];
    [old deliverURL:nil error:[NSError errorWithDomain:@"TouchColor.ProviderFixture" code:2 userInfo:nil] returned:late];
    [self waitForExpectations:@[late] timeout:5];
    XCTAssertTrue(workspace.loading);XCTAssertEqualObjects(workspace.flowStates.lastObject,@YES);
    XCTAssertEqual(workspace.canvas,original);XCTAssertEqual(palette.messages.count,0u);
    [palette cancelPhotoImport];
    [self waitForCondition:^BOOL { return new.loadProgress.cancelled; } description:@"New provider progress is cancelled after registration"];XCTAssertFalse(workspace.loading);XCTAssertEqual(workspace.canvas,original);
}
@end
