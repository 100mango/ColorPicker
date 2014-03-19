//
//  ColorImageView.m
//  ColorPicker
//
//  Created by Mango on 14-2-11.
//  Copyright (c) 2014年 Mango. All rights reserved.
//

#import "ColorImageView.h"

@interface ColorImageView ()
@end



@implementation ColorImageView
- (id)initWithFrame:(CGRect)frame
{
    self = [super initWithFrame:frame];
    if (self)
    {
        //将imageView 设为可接收触摸信息
        self.userInteractionEnabled = YES;
        //设置imageView 的contenMode模式
        self.contentMode = UIViewContentModeScaleAspectFill;
        
        //初始化RGB信息
        self.red = @"255";
        self.green = @"255";
        self.blue = @"255";
        self.hexRGB = @"#FFFFFF";
    }
    return self;
}

-(void)touchesBegan:(NSSet *)touches withEvent:(UIEvent *)event
{
    UITouch *touch = [[event allTouches]anyObject];
    CGPoint point = [touch locationInView:self];
    
    [self getColorOfPoint:point];
}


//获取颜色
- (void) getColorOfPoint:(CGPoint)point
{
    
    unsigned char pixel[4] = {0};
    CGColorSpaceRef colorSpace = CGColorSpaceCreateDeviceRGB();
    CGContextRef context = CGBitmapContextCreate(pixel,
                                                 1, 1, 8, 4, colorSpace, (CGBitmapInfo)kCGImageAlphaPremultipliedLast);
    
    CGContextTranslateCTM(context, -point.x, -point.y);
    
    [self.layer renderInContext:context];
    
    CGContextRelease(context);
    CGColorSpaceRelease(colorSpace);
    UIColor *color = [UIColor colorWithRed:pixel[0]/255.0
                                     green:pixel[1]/255.0
                                      blue:pixel[2]/255.0
                                     alpha:pixel[3]/255.0];
    self.red = [NSString stringWithFormat:@"%d",pixel[0]];
    self.green = [NSString stringWithFormat:@"%d",pixel[1]];
    self.blue = [NSString stringWithFormat:@"%d",pixel[2]];
    self.hexRGB = [NSString stringWithFormat:@"#%x%x%x",pixel[0],pixel[1],pixel[2]];
    self.selectedColor = color;
    
    
    
    //通知Controller更新label和图片
    [[NSNotificationCenter defaultCenter] postNotificationName:@"updateLabelAndColorImage"object:self];
    
    NSLog(@"%@",color);
}


@end
