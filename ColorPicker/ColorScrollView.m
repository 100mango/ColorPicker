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

@interface ColorScrollView ()

@property (strong, nonatomic) ColorPickerImageView *colorPickerView;
@end

@implementation ColorScrollView

- (id)initWithFrame:(CGRect)frame
{
    self = [super initWithFrame:frame];
    if (self)
    {
        _selectedImageView = [[ColorImageView alloc]initWithFrame:CGRectMake(0, 0, 320, 568/2)];
        [self addSubview:self.selectedImageView];
        
        //初始化取色指示器图片
        _colorPickerView =[[ColorPickerImageView alloc]initWithFrame:CGRectMake(0, 0, 78/2, 101/2)];
        self.colorPickerView.image = [UIImage imageNamed:@"CP-针.png"];
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
    CGRect newFrame = self.colorPickerView.frame;
    newFrame.origin.x = point.x;
    newFrame.origin.y = point.y;
    self.colorPickerView.frame = newFrame;
    self.colorPickerView.hidden = NO;
    return YES;
}




@end
