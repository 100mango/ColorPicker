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
#import "Masonry.h"

@interface ColorScrollView ()
@property (strong,nonatomic) UIImageView *pickerView;
@end

@implementation ColorScrollView

- (void)awakeFromNib
{
    [super awakeFromNib];
    
    //初始化背景颜色
    self.backgroundColor = [UIColor colorWithRed:55/255.0 green:55/255.0 blue:54/255.0 alpha:1];
    
    //初始化要放大的Imageview
    _imageView = [[ColorImageView alloc]init];
    [self addSubview:self.imageView];
    [self.imageView mas_makeConstraints:^(MASConstraintMaker *make) {
        make.top.equalTo(@0);
        make.bottom.equalTo(@0);
        make.left.equalTo(@0);
        make.right.equalTo(@0);
    }];
    
    //初始取色器
    _pickerView = [[UIImageView alloc]initWithImage:[UIImage imageNamed:@"picker"]];
    self.pickerView.exclusiveTouch = YES;
    self.pickerView.userInteractionEnabled = YES;
    self.pickerView.hidden = YES;
    [self addSubview:self.pickerView];
 
}

- (BOOL)touchesShouldBegin:(NSSet *)touches withEvent:(UIEvent *)event inContentView:(UIView *)view
{
    //更像点击后的取色器坐标
    UITouch *touch = [[event allTouches]anyObject];
    CGPoint point = [touch locationInView:self];
    self.pickerView.center = point;
    self.pickerView.hidden = NO;
    return YES;
}




@end
