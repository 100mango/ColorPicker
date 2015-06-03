//
//  ColorViewController.m
//  ColorPicker
//
//  Created by Mango on 14-2-5.
//  Copyright (c) 2014年 Mango. All rights reserved.
//

#import "ColorViewController.h"
#import <QuartzCore/QuartzCore.h>

//view
#import "UIView+Tools.h"
#import "ColorImageView.h"
#import "ColorDetectView.h"

@interface ColorViewController ()<ColorDetectViewDelegate>

@property (strong, nonatomic)  ColorDetectView *colorDetectView;
@property (nonatomic,strong) UIImage *image;

@property (weak, nonatomic) IBOutlet UILabel *red;
@property (weak, nonatomic) IBOutlet UILabel *green;
@property (weak, nonatomic) IBOutlet UILabel *blue;
@property (weak, nonatomic) IBOutlet UILabel *hexRGB;
@property (weak, nonatomic) IBOutlet UIView *scrollViewSizeView;
@property (weak, nonatomic) IBOutlet UIButton *saveButton;

@property (weak, nonatomic) IBOutlet UIView *bottomBar;

@end

@implementation ColorViewController

- (void)setChooseImage:(UIImage *)image
{
    //不能在这里直接赋值照片给ColorScrollView 因为ScrollView还为Null
    self.image = image;
}

//设置状态栏
- (BOOL)prefersStatusBarHidden
{
    return YES;
}

- (void)viewDidLoad
{
    [super viewDidLoad];
    
    //setup view
    [self setupBackgroud];
    [self setupScrollView];
    
    //init text
    self.red.text = @"255";
    self.green.text = @"255";
    self.blue.text = @"255";
    self.hexRGB.text = @"#ffffff";
    
}

- (void)viewDidLayoutSubviews
{
    [super viewDidLayoutSubviews];
    
    //update scrollView frame
    // fix reset imageview frame by comparing first
    if (!CGRectEqualToRect(self.colorDetectView.frame,self.scrollViewSizeView.bounds)) {
        self.colorDetectView.frame = self.scrollViewSizeView.bounds;
    }
}

- (void)didReceiveMemoryWarning
{
    [super didReceiveMemoryWarning];
    // Dispose of any resources that can be recreated.
}

#pragma mark -setup View

- (void)setupScrollView
{
    CGRect frame = self.scrollViewSizeView.bounds;
    _colorDetectView = [[ColorDetectView alloc]initWithFrame:frame andUIImage:self.image];
    self.colorDetectView.delegate = self;
    [self.scrollViewSizeView addSubview:self.colorDetectView];
}

- (void)setupBackgroud
{
    //设置背景颜色
    self.view.backgroundColor = [UIColor colorWithRed:239.0/255 green:239.0/255 blue:237.0/255 alpha:1.0];
}

#pragma mark -Action
- (IBAction)saveColor:(UIButton *)sender
{
    self.saveButton.selected = YES;
    dispatch_async(dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT, 0), ^{
        
        NSUserDefaults * userDefaults = [NSUserDefaults standardUserDefaults];
        NSArray * colorArray = [userDefaults arrayForKey:@"colorArray"];
        
        if (colorArray == nil)
        {
            NSArray * newColorArray = @[self.hexRGB.text];
            [userDefaults setObject:newColorArray forKey:@"colorArray"];
        }
        else
        {
            NSMutableArray *newColorArray = [colorArray mutableCopy];
            [newColorArray addObject:self.hexRGB.text];
            [userDefaults setObject:newColorArray forKey:@"colorArray"];
        }
        [userDefaults synchronize];
        
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.8 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
            self.saveButton.selected = NO;
        });
        
    });
}

#pragma mark -colorDetectView delegate

-(UIView *)viewForZoomingInScrollView:(UIScrollView *)scrollView
{
    return self.colorDetectView.imageView;
}

- (void)handelColor:(NSString *)hexColor
{
    [self setColorInformationWith:hexColor];
}

- (void)setColorInformationWith:(NSString*)hexColor
{
    //转换hex值
    unsigned int red ,green,blue;
    
    NSScanner *scanner = [NSScanner scannerWithString:[hexColor substringWithRange:NSMakeRange(1, 2)]];
    [scanner scanHexInt:&red];
    
    scanner = [NSScanner scannerWithString:[hexColor substringWithRange:NSMakeRange(3, 2)]];
    [scanner scanHexInt:&green];
    
    scanner = [NSScanner scannerWithString:[hexColor substringWithRange:NSMakeRange(5, 2)]];
    [scanner scanHexInt:&blue];
    
    
    self.red.text = [NSString stringWithFormat:@"%d",red];
    self.green.text = [NSString stringWithFormat:@"%d",green];
    self.blue.text = [NSString stringWithFormat:@"%d",blue];
    self.hexRGB.text = hexColor;
    
    self.saveButton.backgroundColor = [UIColor colorWithRed:red/255.0 green:green/255.0 blue:blue/255.0 alpha:1];
}
@end
