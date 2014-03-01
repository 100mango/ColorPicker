//
//  ColorRealTimeViewController.m
//  ColorPicker
//
//  Created by Mango on 14-2-11.
//  Copyright (c) 2014年 Mango. All rights reserved.
//

#import "ColorRealTimeViewController.h"
#import <AVFoundation/AVFoundation.h>

@interface ColorRealTimeViewController ()

@property (strong,nonatomic) AVCaptureSession *session;
@property (strong,nonatomic) UIButton *backButton;
@property (strong,nonatomic) CALayer *realTimeLayer;

@end

@implementation ColorRealTimeViewController

- (id)initWithNibName:(NSString *)nibNameOrNil bundle:(NSBundle *)nibBundleOrNil
{
    self = [super initWithNibName:nibNameOrNil bundle:nibBundleOrNil];
    if (self) {
    }
    return self;
}

- (void)viewDidLoad
{
    [super viewDidLoad];
    //开始实时化取景
    [self startCamera];
    
    //初始化按钮
    _backButton = [UIButton buttonWithType:UIButtonTypeCustom];
    self.backButton.frame = CGRectMake(30/2, 64/2, 20, 20);
    [self.backButton setImage:[UIImage imageNamed:@"30x64.png"] forState:UIControlStateNormal];
    [self.backButton addTarget:self action:@selector(back) forControlEvents:UIControlEventTouchUpInside];
    [self.view addSubview:self.backButton];
}

- (void)back
{
    [self.presentingViewController dismissViewControllerAnimated:YES completion:nil];
}

- (void)startCamera
{
    // Create the capture session
    _session = [[AVCaptureSession alloc]init];
    [self.session setSessionPreset:AVCaptureSessionPresetMedium];
    // Capture device
    AVCaptureDevice *captureDevice = [AVCaptureDevice defaultDeviceWithMediaType:AVMediaTypeVideo];
    // Device input
    AVCaptureDeviceInput *deviceInput = [AVCaptureDeviceInput deviceInputWithDevice:captureDevice error:nil];
    if ([self.session canAddInput:deviceInput])
    {
        [self.session addInput:deviceInput];
    }
    
    // Initialize image output
    AVCaptureVideoDataOutput *output = [AVCaptureVideoDataOutput new];
    
    NSDictionary *rgbOutputSettings = [NSDictionary dictionaryWithObject:
                                       [NSNumber numberWithInt:kCMPixelFormat_32BGRA] forKey:(id)kCVPixelBufferPixelFormatTypeKey];
    [output setVideoSettings:rgbOutputSettings];
    [output setAlwaysDiscardsLateVideoFrames:YES];
    if( [self.session canAddOutput:output] )
    {
        [self.session addOutput:output];
    }
    
    //将output添加进新的线程中
    dispatch_queue_t videoDataOutputQueue = dispatch_queue_create("VideoDataOutputQueue", DISPATCH_QUEUE_SERIAL);
    [output setSampleBufferDelegate:self queue:videoDataOutputQueue];
    [[output connectionWithMediaType:AVMediaTypeVideo] setEnabled:YES];
    
    //生成呈现内容的layer
    _realTimeLayer = [CALayer layer];
    self.realTimeLayer.bounds = CGRectMake(0, 0, self.view.frame.size.height, self.view.frame.size.width);
    self.realTimeLayer.position = CGPointMake(self.view.frame.size.width/2., self.view.frame.size.height/2.);
    self.realTimeLayer.affineTransform = CGAffineTransformMakeRotation(M_PI/2);
    [self.view.layer addSublayer:self.realTimeLayer];

    //开始
    [self.session startRunning];
}

- (void)didReceiveMemoryWarning
{
    [super didReceiveMemoryWarning];
    // Dispose of any resources that can be recreated.
}

-(void)touchesBegan:(NSSet *)touches withEvent:(UIEvent *)event
{
    UITouch *touch = [[event allTouches]anyObject];
    CGPoint point = [touch locationInView:self.view];
    [self getColorOfPoint:point];
}

- (void) getColorOfPoint:(CGPoint)point
{
    printf("x:%f ,Y:%f \n",point.x,point.y);
    
    unsigned char pixel[4] = {0};
    CGColorSpaceRef colorSpace = CGColorSpaceCreateDeviceRGB();
    CGContextRef context = CGBitmapContextCreate(pixel,
                                                 1, 1, 8, 4, colorSpace, (CGBitmapInfo)kCGImageAlphaPremultipliedLast);
    
    CGContextTranslateCTM(context, -point.x, -point.y);
    
    [self.realTimeLayer renderInContext:context];
    
    CGContextRelease(context);
    CGColorSpaceRelease(colorSpace);
    UIColor *color = [UIColor colorWithRed:pixel[0]/255.0
                                     green:pixel[1]/255.0
                                      blue:pixel[2]/255.0
                                     alpha:pixel[3]/255.0];
    NSLog(@"%@",color);
}


- (void)captureOutput:(AVCaptureOutput *)captureOutput didOutputSampleBuffer:(CMSampleBufferRef)sampleBuffer  fromConnection:(AVCaptureConnection *)connection
{
    
    CVImageBufferRef imageBuffer = CMSampleBufferGetImageBuffer(sampleBuffer);
    CVPixelBufferLockBaseAddress(imageBuffer,0);        // Lock the image buffer
    
    uint8_t *baseAddress = (uint8_t *)CVPixelBufferGetBaseAddressOfPlane(imageBuffer, 0);   // Get information of the image
    size_t bytesPerRow = CVPixelBufferGetBytesPerRow(imageBuffer);
    size_t width = CVPixelBufferGetWidth(imageBuffer);
    size_t height = CVPixelBufferGetHeight(imageBuffer);
    CGColorSpaceRef colorSpace = CGColorSpaceCreateDeviceRGB();
    
    CGContextRef newContext = CGBitmapContextCreate(baseAddress, width, height, 8, bytesPerRow, colorSpace, kCGBitmapByteOrder32Little | kCGImageAlphaPremultipliedFirst);
    CGImageRef newImage = CGBitmapContextCreateImage(newContext);
    //呈现内容
    dispatch_sync(dispatch_get_main_queue(), ^{
        self.realTimeLayer.contents = (__bridge id)(newImage);
    });
    
    CGContextRelease(newContext);
    CGColorSpaceRelease(colorSpace);
    CVPixelBufferUnlockBaseAddress(imageBuffer,0);
    
}



@end
