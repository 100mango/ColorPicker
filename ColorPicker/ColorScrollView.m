//
//  ColorScrollView.m
//  ColorPicker
//
//  Created by Mango on 14-2-11.
//  Copyright (c) 2014年 Mango. All rights reserved.
//

#import "ColorScrollView.h"
#import "ColorImageView.h"
#import "ColorPickerImageView.h"
#define DEVICE_IS_IPHONE5 ([[UIScreen mainScreen] bounds].size.height == 568)

@interface ColorScrollView ()

@end

@implementation ColorScrollView

- (id)initWithFrame:(CGRect)frame
{
    self = [super initWithFrame:frame];
    if (self)
    {
        //设置裁剪
        self.clipsToBounds = YES;
        //初始化背景颜色
        self.backgroundColor = [UIColor colorWithRed:55/255.0 green:55/255.0 blue:54/255.0 alpha:1];
        //初始化要放大的Imageview
        if (DEVICE_IS_IPHONE5) {
            _selectedImageView = [[ColorImageView alloc]initWithFrame:CGRectMake(0, 0, 320, 745/2)];
        }
        else
        {
            _selectedImageView = [[ColorImageView alloc]initWithFrame:CGRectMake(0, 0, 320, 568/2)];
        }
        [self addSubview:self.selectedImageView];
        
        //初始化取色指示器图片
        _colorPickerView =[[ColorPickerImageView alloc]initWithFrame:CGRectMake(0, 0, 50/2, 50/2)];
        self.colorPickerView.image = [UIImage imageNamed:@"picker"];
        self.colorPickerView.hidden = YES;
        self.colorPickerView.exclusiveTouch = YES;
        self.colorPickerView.userInteractionEnabled = YES;
        self.colorPickerView.imageView = self.selectedImageView;
        [self addSubview:self.colorPickerView];
    }
    return self;
}

- (BOOL)touchesShouldBegin:(NSSet *)touches withEvent:(UIEvent *)event inContentView:(UIView *)view
{
    //更像点击后的指示器坐标
    UITouch *touch = [[event allTouches]anyObject];
    CGPoint point = [touch locationInView:self];
    self.colorPickerView.center = point;
    self.colorPickerView.hidden = NO;
    return YES;
}




@end
