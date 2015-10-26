//
//  ColorScrollView.m
//  ColorPicker
//
//  Created by Mango on 14-2-11.
//  Copyright (c) 2014年 Mango. All rights reserved.
//

#import "ColorDetectView.h"
#import "Masonry.h"

@interface ColorDetectView ()
@property (strong,nonatomic) UIImageView *pickerView;
@property (strong,readwrite,nonatomic) UIImageView *imageView;
@property (assign,nonatomic) CGPoint pointInImageView;
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
        [self.pinchGestureRecognizer addTarget:self action:@selector(handelPinchGeture:)];

        UITapGestureRecognizer *tap = [[UITapGestureRecognizer alloc]initWithTarget:self action:@selector(handelTapGesture:)];
        [self addGestureRecognizer:tap];
        [self.imageView addGestureRecognizer:tap];
        
        
        //初始化要放大的Imageview
        self.imageView = [[UIImageView alloc]initWithFrame:self.bounds];
        self.imageView.image = image;
        self.imageView.contentMode = UIViewContentModeScaleAspectFit;
        [self addSubview:self.imageView];
        
        //初始取色器
        UIPanGestureRecognizer *pan = [[UIPanGestureRecognizer alloc]initWithTarget:self action:@selector(handelPangesture:)];
        self.pickerView = [[UIImageView alloc]initWithImage:[UIImage imageNamed:@"picker"]];
        [self.pickerView addGestureRecognizer:pan];
        //self.pickerView.exclusiveTouch = YES;
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

- (void)handelColor:(NSString *)hexColor
{
    [self.delegate handelColor:hexColor];
}

- (void) getColorOfPoint:(CGPoint)point InView:(UIView*)view
{
    
    unsigned char pixel[4] = {0};
    CGColorSpaceRef colorSpace = CGColorSpaceCreateDeviceRGB();
    CGContextRef context = CGBitmapContextCreate(pixel,
                                                 1, 1, 8, 4, colorSpace, (CGBitmapInfo)kCGImageAlphaPremultipliedLast);
    
    CGContextTranslateCTM(context, -point.x, -point.y);
    
    [view.layer renderInContext:context];
    
    CGContextRelease(context);
    CGColorSpaceRelease(colorSpace);
    
    NSString *hexColor = [NSString stringWithFormat:@"#%02x%02x%02x",pixel[0],pixel[1],pixel[2]];
    
    [self.delegate handelColor:hexColor];
}


#pragma mark - tap gesture delegate
- (void)handelTapGesture:(UITapGestureRecognizer*)gesture
{
    CGPoint point = [gesture locationInView:self];
    self.pointInImageView = [gesture locationInView:self.imageView];
    self.pickerView.center = point;
    self.pickerView.hidden = NO;
    [self getColorOfPoint:self.pointInImageView InView:self.imageView];
    
}

#pragma mark - pinch gesture delegate
- (void)handelPinchGeture:(UIPinchGestureRecognizer*)gesture
{
    if (gesture.state == UIGestureRecognizerStateChanged) {
        self.pickerView.center = [self convertPoint:self.pointInImageView fromView:self.imageView];
    }
}

#pragma mark - pan gesture delegate
- (void)handelPangesture:(UIPanGestureRecognizer*)gesture
{
    if (gesture.state == UIGestureRecognizerStateChanged) {
        self.pickerView.center = [gesture locationInView:self];
        [self getColorOfPoint:[gesture locationInView:self.imageView] InView:self.imageView];
    }
}


@end
