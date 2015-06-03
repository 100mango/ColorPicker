//
//  ColorScrollView.m
//  ColorPicker
//
//  Created by Mango on 14-2-11.
//  Copyright (c) 2014年 Mango. All rights reserved.
//

#import "ColorDetectView.h"
#import "ColorImageView.h"
#import "Masonry.h"

@interface ColorDetectView ()<ColorImageViewDelegate>
@property (strong,nonatomic) UIImageView *pickerView;
@property (strong,readwrite,nonatomic) ColorImageView *imageView;
@end

@implementation ColorDetectView

@dynamic delegate;

- (instancetype)initWithFrame:(CGRect)frame andUIImage:(UIImage *)image
{
    self = [super initWithFrame:frame];
    if (self)
    {
        //初始化自身设置
        self.maximumZoomScale = 100.0;
        self.minimumZoomScale = 1.0;
        self.contentSize = frame.size;
        self.bounces = NO;
        self.bouncesZoom = NO; //禁止缩小至最小比例之下
        self.backgroundColor = [UIColor colorWithRed:55/255.0 green:55/255.0 blue:54/255.0 alpha:1];

        //初始化要放大的Imageview
        self.imageView = [[ColorImageView alloc]initWithFrame:self.bounds];
        self.imageView.image = image;
        self.imageView.delegate = self;
        [self addSubview:self.imageView];
        
        //DLog(@"%@",self);
        //DLog(@"%@",self.imageView);
        
        //初始取色器
        _pickerView = [[UIImageView alloc]initWithImage:[UIImage imageNamed:@"picker"]];
        self.pickerView.exclusiveTouch = YES;
        self.pickerView.userInteractionEnabled = YES;
        self.pickerView.hidden = YES;
        [self addSubview:self.pickerView];
        
    }
    return self;
}


- (void)setFrame:(CGRect)frame
{
    [super setFrame:frame];
    self.imageView.frame = frame;
}


- (BOOL)touchesShouldBegin:(NSSet *)touches withEvent:(UIEvent *)event inContentView:(UIView *)view
{
    //更新点击后的取色器坐标
    UITouch *touch = [[event allTouches]anyObject];
    CGPoint point = [touch locationInView:self];
    self.pickerView.center = point;
    self.pickerView.hidden = NO;
    return YES;
}


- (void)handelColor:(NSString *)hexColor
{
    [self.delegate handelColor:hexColor];
}

@end
