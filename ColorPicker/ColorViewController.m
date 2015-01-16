//
//  ColorViewController.m
//  ColorPicker
//
//  Created by Mango on 14-2-5.
//  Copyright (c) 2014年 Mango. All rights reserved.
//

#import "ColorViewController.h"
#import <QuartzCore/QuartzCore.h>
#import "ColorImageView.h"
#import "ColorScrollView.h"
#import "ColorPickerImageView.h"
#define DEVICE_IS_IPHONE5 ([[UIScreen mainScreen] bounds].size.height == 568)

@interface ColorViewController ()

@property (weak, nonatomic) IBOutlet ColorScrollView *colorScrollView;
@property (nonatomic,strong) UIImage *image;

@property (weak, nonatomic) IBOutlet UILabel *red;
@property (weak, nonatomic) IBOutlet UILabel *green;
@property (weak, nonatomic) IBOutlet UILabel *blue;
@property (weak, nonatomic) IBOutlet UILabel *hexRGB;

@property (strong, nonatomic) UIImageView *selectedColoImformationView;

@property (strong, nonatomic) UIButton *backButton;
@property (strong, nonatomic) UISlider *slider;
@property (strong, nonatomic) UIButton *saveButton;

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
    self.colorScrollView.imageView.image = self.image;
    [self setupBackgroud];
    
    
    //init data
    self.red.text = self.colorScrollView.imageView.red;
    self.green.text = self.colorScrollView.imageView.green;
    self.blue.text = self.colorScrollView.imageView.blue;
    self.hexRGB.text = self.colorScrollView.imageView.hexRGB;
    
    //注册到通知中心用于更新label
    NSString * updateLabel = @"updateLabelAndColorImage";
    [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(updateLabelAndColorImage) name:updateLabel object:nil];
}

- (void)didReceiveMemoryWarning
{
    [super didReceiveMemoryWarning];
    // Dispose of any resources that can be recreated.
}

#pragma mark -setup View

- (void)setupBackgroud
{
    //设置背景颜色
    self.view.backgroundColor = [UIColor colorWithRed:239.0/255 green:239.0/255 blue:237.0/255 alpha:1.0];
    
    UIBarButtonItem *saveButton = [[UIBarButtonItem alloc]initWithTitle:@"保存" style:UIBarButtonItemStylePlain target:self action:@selector(saveColor)];
    self.navigationItem.rightBarButtonItem = saveButton;
}

#pragma mark -Action

- (void)saveColor
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

#pragma - notification center
-(void)updateLabelAndColorImage
{
    self.red.text = self.colorScrollView.imageView.red;
    self.green.text = self.colorScrollView.imageView.green;
    self.blue.text = self.colorScrollView.imageView.blue;
    self.hexRGB.text = self.colorScrollView.imageView.hexRGB;
    self.selectedColoImformationView.backgroundColor = self.colorScrollView.imageView.selectedColor;
}


@end
