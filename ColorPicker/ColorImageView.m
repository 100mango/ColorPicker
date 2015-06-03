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
        self.contentMode = UIViewContentModeScaleAspectFit;
        
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
    
    NSString *hexColor = [NSString stringWithFormat:@"#%02x%02x%02x",pixel[0],pixel[1],pixel[2]];
    
    [self.delegate handelColor:hexColor];
}


@end
