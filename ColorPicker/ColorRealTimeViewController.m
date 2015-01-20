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
#define DEVICE_IS_IPHONE5 ([[UIScreen mainScreen] bounds].size.height == 568)

@interface ColorRealTimeViewController ()
{
    CALayer *trackingDot;
    
    GPUImageVideoCamera *videoCamera;
    GPUImageFilter *thresholdFilter, *positionFilter;
    GPUImageRawDataOutput *positionRawData, *videoRawData;
    GPUImageAverageColor *positionAverageColor;
    GPUImageView *filteredVideoView;
    
    
    BOOL shouldReplaceThresholdColor;
    CGPoint currentTouchPoint;
    GLfloat thresholdSensitivity;
    GPUVector3 thresholdColor;
}

@property (strong,nonatomic) UIButton *backButton;
@property (strong,nonatomic) UIButton *saveButton;
//@property (strong,nonatomic) GPUImageVideoCamera *videoCamera;
//@property (strong,nonatomic) GPUImageRawDataOutput *videoRawData;
//@property (strong,nonatomic) GPUImageView *VideoView;
@property (weak, nonatomic) IBOutlet GPUImageView *VideoView;
@property (strong,nonatomic) UILabel *red;
@property (strong,nonatomic) UILabel *green;
@property (strong,nonatomic) UILabel *blue;
@property (strong,nonatomic) NSString *hexRGB;
@property (strong,nonatomic) UIImageView *labelBackground;
@property (strong,nonatomic) UIImageView *colorVIewCircle;
@property (strong,nonatomic) UIColor *pointColor;
@property (strong,nonatomic) UIView *colorView;
@end

@implementation ColorRealTimeViewController

//设置状态栏
- (BOOL)prefersStatusBarHidden{
    return YES;
}

- (void)viewDidLoad
{
    [super viewDidLoad];

    //[self setupGPUImage];
    [self setupButton];
    [self setupLabels];
    [self setupColorPointView];

}

- (void)viewDidAppear:(BOOL)animated
{
    [super viewDidAppear:animated];
    [self setupGPUImage];

}


#pragma setupView
- (void)setupButton
{
    _backButton = [UIButton buttonWithType:UIButtonTypeCustom];
    self.backButton.frame = CGRectMake(0, 23/2, 105/2, 96/2);
    [self.backButton setImage:[UIImage imageNamed:@"0,23"] forState:UIControlStateNormal];
    [self.backButton setImage:[UIImage imageNamed:@"0,23 B"] forState:UIControlStateHighlighted];
    [self.backButton addTarget:self action:@selector(back) forControlEvents:UIControlEventTouchUpInside];
    [self.view addSubview:self.backButton];
    
    _saveButton = [UIButton buttonWithType:UIButtonTypeCustom];
    if (DEVICE_IS_IPHONE5) {
        self.saveButton.frame = CGRectMake(500/2, 884/2 + 176/2, 140/2, 77/2);
    }
    else
    {
        self.saveButton.frame = CGRectMake(500/2, 884/2, 140/2, 77/2);
    }
    [self.saveButton setImage:[UIImage imageNamed:@"500,883"] forState:UIControlStateNormal];
    [self.saveButton setImage:[UIImage imageNamed:@"500,883 B"] forState:UIControlStateHighlighted];
    [self.saveButton setImage:[UIImage imageNamed:@"500,883 C"] forState:UIControlStateSelected];
    [self.saveButton addTarget:self action:@selector(save) forControlEvents:UIControlEventTouchUpInside];
    [self.view addSubview:self.saveButton];
    
}

- (void)setupLabels
{
    if (DEVICE_IS_IPHONE5) {
        _labelBackground = [[UIImageView alloc]initWithFrame:CGRectMake(0, 818/2 + 176/2, 171/2, 143/2)];
        _red = [[UILabel alloc]initWithFrame:CGRectMake(74/2, 820/2 + 176/2, 40, 40)];
        _green = [[UILabel alloc]initWithFrame:CGRectMake(74/2, 860/2 + 176/2, 40, 40)];
        _blue = [[UILabel alloc]initWithFrame:CGRectMake(74/2, 900/2 + 176/2, 40, 40)];
    }
    else
    {
        _labelBackground = [[UIImageView alloc]initWithFrame:CGRectMake(0, 818/2, 171/2, 143/2)];
        _red = [[UILabel alloc]initWithFrame:CGRectMake(74/2, 820/2, 40, 40)];
        _green = [[UILabel alloc]initWithFrame:CGRectMake(74/2, 860/2, 40, 40)];
        _blue = [[UILabel alloc]initWithFrame:CGRectMake(74/2, 900/2, 40, 40)];
    }
    self.labelBackground.image = [UIImage imageNamed:@"0,817"];
    [self.view addSubview:self.labelBackground];
    
    self.red.text = @"255";
    self.green.text = @"255";
    self.blue.text = @"255";
    
    [self.view addSubview:self.red];
    [self.view addSubview:self.green];
    [self.view addSubview:self.blue];
}

- (void)setupColorPointView
{
    if (DEVICE_IS_IPHONE5) {
        _colorVIewCircle = [[UIImageView alloc]initWithFrame:CGRectMake(320/2 - 45/2, 568/2 -45/2, 45, 45)];
        _colorView = [[UIView alloc]initWithFrame:CGRectMake(320/2 - 46/2/2,568/2  - 46/2/2, 46/2, 46/2)];

    }
    else
    {
        _colorVIewCircle = [[UIImageView alloc]initWithFrame:CGRectMake(320/2 - 45/2, 480/2 -45/2, 45, 45)];
        _colorView = [[UIView alloc]initWithFrame:CGRectMake(320/2 - 46/2/2,480/2  - 46/2/2, 46/2, 46/2)];

    }
    self.colorVIewCircle.image = [UIImage imageNamed:@"275,436"];
    self.colorView.backgroundColor = [UIColor clearColor];
    self.colorView.layer.cornerRadius = 46/2/2;
    
    [self.view addSubview:self.colorView];
    [self.view addSubview:self.colorVIewCircle];
}

- (void)setupGPUImage
{
    //设置Camera
    //_videoCamera = [[GPUImageVideoCamera alloc]initWithSessionPreset:AVCaptureSessionPreset640x480 cameraPosition:AVCaptureDevicePositionBack];
    //self.videoCamera.outputImageOrientation = UIInterfaceOrientationPortrait;
    
    //设置videoView
    /*
    if (DEVICE_IS_IPHONE5) {
        _VideoView = [[GPUImageView alloc]initWithFrame:CGRectMake(0, 0, 320, 568)];
    }
    else
    {
        _VideoView = [[GPUImageView alloc]initWithFrame:CGRectMake(0, 0, 320, 480)];
    }*/
    
    //self.VideoView.fillMode = kGPUImageFillModePreserveAspectRatioAndFill;
    //[self.view addSubview:self.VideoView];
    
    /*
    //设置output Rawdata
    CGSize videoPixelSize = CGSizeMake(480.0, 640.0);
    _videoRawData = [[GPUImageRawDataOutput alloc]initWithImageSize:videoPixelSize resultsInBGRAFormat:YES];
    
    //设置output回调
    __weak ColorRealTimeViewController *safeSelf = self;
    [self.videoRawData setNewFrameAvailableBlock:^{
        
        CGPoint focusPoint = {480/2,640/2};
        
        GPUByteColorVector colorAtTouchPoint = [safeSelf.videoRawData colorAtLocation:focusPoint];
        
        dispatch_async(dispatch_get_main_queue(), ^{
            
            int red = (int)colorAtTouchPoint.red;
            int green = (int)colorAtTouchPoint.green;
            int blue = (int)colorAtTouchPoint.blue;
            
            safeSelf.red.text = [NSString stringWithFormat:@"%d",red];
            safeSelf.green.text = [NSString stringWithFormat:@"%d",green];
            safeSelf.blue.text = [NSString stringWithFormat:@"%d",blue];
            safeSelf.hexRGB = [NSString stringWithFormat:@"#%02x%02x%02x",red,green,blue];

            
            safeSelf.pointColor = [UIColor colorWithRed:red/255.0 green:green/255.0 blue:blue/255.0 alpha:1];
            safeSelf.colorView.backgroundColor = safeSelf.pointColor;
        });
        
    }];
    
    //开始录制
    [self.videoCamera addTarget:self.VideoView];
    [self.videoCamera addTarget:self.videoRawData];
    [self.videoCamera startCameraCapture];
     */
    
    
    videoCamera = [[GPUImageVideoCamera alloc] initWithSessionPreset:AVCaptureSessionPreset640x480 cameraPosition:AVCaptureDevicePositionBack];
    videoCamera.outputImageOrientation = UIInterfaceOrientationPortrait;
    CGSize videoPixelSize = CGSizeMake(480.0, 640.0);
    CGRect mainScreenFrame = [[UIScreen mainScreen] applicationFrame];

    filteredVideoView = [[GPUImageView alloc] initWithFrame:CGRectMake(0.0, 0.0, mainScreenFrame.size.width, mainScreenFrame.size.height)];
    [self.view addSubview:filteredVideoView];
    
    __unsafe_unretained ColorRealTimeViewController *weakSelf = self;
    
    videoRawData = [[GPUImageRawDataOutput alloc] initWithImageSize:videoPixelSize resultsInBGRAFormat:YES];
    [videoRawData setNewFrameAvailableBlock:^{
            
        
        CGPoint focusPoint = {480/2,640/2};
        
        
        GPUByteColorVector colorAtTouchPoint = [weakSelf->videoRawData colorAtLocation:focusPoint];
        
        NSLog(@"Color at touch point: %d, %d, %d, %d", colorAtTouchPoint.red, colorAtTouchPoint.green, colorAtTouchPoint.blue, colorAtTouchPoint.alpha);
        
        }];
    
    
    [videoCamera addTarget:filteredVideoView];
    [videoCamera addTarget:videoRawData];
    [videoCamera startCameraCapture];
}

#pragma mark -buttonEvent
- (void)back
{
    [self.presentingViewController dismissViewControllerAnimated:YES completion:nil];
}

- (void)save
{
    self.saveButton.selected = YES;
    dispatch_async(dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT, 0), ^{
        
        NSUserDefaults * userDefaults = [NSUserDefaults standardUserDefaults];
        NSArray * colorArray = [userDefaults arrayForKey:@"colorArray"];
        
        if (colorArray == nil)
        {
            NSArray * newColorArray = @[self.hexRGB];
            [userDefaults setObject:newColorArray forKey:@"colorArray"];
        }
        else
        {
            NSMutableArray *newColorArray = [colorArray mutableCopy];
            [newColorArray addObject:self.hexRGB];
            [userDefaults setObject:newColorArray forKey:@"colorArray"];
        }
        [userDefaults synchronize];
        
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.8 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
            self.saveButton.selected = NO;
        });
        
    });
}

@end
