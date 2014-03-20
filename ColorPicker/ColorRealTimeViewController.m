//
//  ColorRealTimeViewController.m
//  ColorPicker
//
//  Created by Mango on 14-2-11.
//  Copyright (c) 2014年 Mango. All rights reserved.
//

#import "ColorRealTimeViewController.h"
#import <AVFoundation/AVFoundation.h>
#import "GPUImage.h"

@interface ColorRealTimeViewController ()


//@property (strong,nonatomic) AVCaptureSession *session;
@property (strong,nonatomic) UIButton *backButton;
/*
@property (strong,nonatomic) CALayer *realTimeLayer;
@property (strong,nonatomic) AVCaptureVideoPreviewLayer *previewLayer;
@property (strong,nonatomic) NSTimer *timer;
@property BOOL flag;
 */

@property (strong,nonatomic) GPUImageVideoCamera *videoCamera;
@property (strong,nonatomic) GPUImageRawDataOutput *videoRawData;
@property (strong,nonatomic) GPUImageView *VideoView;
@property (nonatomic) CGPoint currentPoint;
@property (strong,nonatomic) UILabel *red;
@property (strong,nonatomic) UILabel *green;
@property (strong,nonatomic) UILabel *blue;

@property BOOL isTouch;

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
    
    _isTouch = NO;
    
    [self setupGPUImage];
    [self setupButton];
    [self setupLabels];
    

}


#pragma setupView
- (void)setupButton
{
    _backButton = [UIButton buttonWithType:UIButtonTypeCustom];
    self.backButton.frame = CGRectMake(30/2, 64/2, 20, 20);
    [self.backButton setImage:[UIImage imageNamed:@"30x64.png"] forState:UIControlStateNormal];
    [self.backButton addTarget:self action:@selector(back) forControlEvents:UIControlEventTouchUpInside];
    [self.view addSubview:self.backButton];
}

- (void)setupLabels
{
    _red = [[UILabel alloc]initWithFrame:CGRectMake(20, 60, 40, 40)];
    _blue = [[UILabel alloc]initWithFrame:CGRectMake(20, 100, 40, 40)];
    _green = [[UILabel alloc]initWithFrame:CGRectMake(20, 140, 40, 40)];
    
    self.red.text = @"255";
    self.green.text = @"255";
    self.blue.text = @"255";
    
    [self.view addSubview:self.red];
    [self.view addSubview:self.green];
    [self.view addSubview:self.blue];
}

- (void)setupGPUImage
{
    //设置Camera
    _videoCamera = [[GPUImageVideoCamera alloc]initWithSessionPreset:AVCaptureSessionPreset640x480 cameraPosition:AVCaptureDevicePositionBack];
    self.videoCamera.outputImageOrientation = UIInterfaceOrientationPortrait;
    
    //设置videoView
    CGRect mainScreenFrame = [[UIScreen mainScreen]applicationFrame];
    _VideoView = [[GPUImageView alloc]initWithFrame:CGRectMake(0, 0, mainScreenFrame.size.width, mainScreenFrame.size.height)];
    [self.view addSubview:self.VideoView];
    
    //设置output Rawdata
    CGSize videoPixelSize = CGSizeMake(480, 640);
    _videoRawData = [[GPUImageRawDataOutput alloc]initWithImageSize:videoPixelSize resultsInBGRAFormat:YES];
    
    //设置output回调
    __weak ColorRealTimeViewController *safeSelf = self;
    [self.videoRawData setNewFrameAvailableBlock:^{
        
        if (safeSelf.isTouch == YES) {
            CGSize currentViewSize = safeSelf.view.bounds.size;
            CGSize rawPixelsSize = [safeSelf.videoRawData maximumOutputSize];
            
            CGPoint scaledTouchPoint;
            scaledTouchPoint.x = (safeSelf.currentPoint.x / currentViewSize.width) * rawPixelsSize.width;
            scaledTouchPoint.y = (safeSelf.currentPoint.y / currentViewSize.height) * rawPixelsSize.height;
            
            GPUByteColorVector colorAtTouchPoint = [safeSelf.videoRawData colorAtLocation:scaledTouchPoint];
            NSLog(@"%d",(int)colorAtTouchPoint.red);
            
            dispatch_async(dispatch_get_main_queue(), ^{
                safeSelf.red.text = [NSString stringWithFormat:@"%d",(int)colorAtTouchPoint.red];
                safeSelf.green.text = [NSString stringWithFormat:@"%d",(int)colorAtTouchPoint.green];
                safeSelf.blue.text = [NSString stringWithFormat:@"%d",(int)colorAtTouchPoint.blue];
            });
            
            safeSelf.isTouch = NO;
        }
        
    }];
    
    //开始录制
    [self.videoCamera addTarget:self.VideoView];
    [self.videoCamera addTarget:self.videoRawData];
    [self.videoCamera startCameraCapture];
    
}

#pragma mark -buttonEvent
- (void)back
{
    [self.presentingViewController dismissViewControllerAnimated:YES completion:nil];
}

#pragma mark -touchEvent
-(void)touchesBegan:(NSSet *)touches withEvent:(UIEvent *)event
{
    self.currentPoint = [[touches anyObject] locationInView:self.view];
    self.isTouch = YES;
    
    //UITouch *touch = [[event allTouches]anyObject];
    //self.currentPoint = [touch locationInView:self.view];
    //self.isTouch = YES;
    //[self getColorOfPoint:point];
}





/*
- (void)startCamera
{
    // Create the capture session
    _session = [[AVCaptureSession alloc]init];
    [self.session setSessionPreset:AVCaptureSessionPresetHigh];
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
    
    //生成提取信息内容的layer
    _realTimeLayer = [CALayer layer];
    self.realTimeLayer.bounds = CGRectMake(0, 0, self.view.frame.size.height, self.view.frame.size.width);
    self.realTimeLayer.position = CGPointMake(self.view.frame.size.width/2., self.view.frame.size.height/2.);
    self.realTimeLayer.affineTransform = CGAffineTransformMakeRotation(M_PI/2);
    //[self.view.layer addSublayer:self.realTimeLayer];

    //生成previewlayer
    _previewLayer = [[AVCaptureVideoPreviewLayer alloc]initWithSession:self.session];
    CGRect bounds = self.view.layer.bounds;
    self.previewLayer.videoGravity = AVLayerVideoGravityResizeAspectFill;
    self.previewLayer.bounds = bounds;
    self.previewLayer.position = CGPointMake(CGRectGetMidX(bounds), CGRectGetMidY(bounds));
    [self.view.layer addSublayer:self.previewLayer];
    
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
    if ( self.flag == YES)
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
        
        //重置flag
        self.flag = NO;
        double delayInSeconds = 1.0;
        dispatch_time_t popTime = dispatch_time(DISPATCH_TIME_NOW, (int64_t)(delayInSeconds * NSEC_PER_SEC));
        dispatch_after(popTime, dispatch_get_main_queue(), ^(void){
            NSLog(@"we come herwe");
            self.flag = YES;
        });
        //_timer = [NSTimer scheduledTimerWithTimeInterval:1.0 target:self selector:@selector(updateFlag) userInfo:nil repeats:NO];
        //[[NSRunLoop currentRunLoop] addTimer:self.timer forMode:NSDefaultRunLoopMode];
    }
 
    
}

*/
@end
