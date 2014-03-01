//
//  ColorPickerImageView.m
//  ColorPicker
//
//  Created by Mango on 14-2-21.
//  Copyright (c) 2014年 Mango. All rights reserved.
//

#import "ColorPickerImageView.h"
#import "ColorImageView.h"

@interface ColorPickerImageView ()
@end
@implementation ColorPickerImageView

- (id)initWithFrame:(CGRect)frame
{
    self = [super initWithFrame:frame];
    if (self)
    {
        UIPanGestureRecognizer *panRecognizer = [[UIPanGestureRecognizer alloc]initWithTarget:self action:@selector(handleGesture:)];
        panRecognizer.maximumNumberOfTouches = 1;
        panRecognizer.minimumNumberOfTouches = 1;
        [self addGestureRecognizer:panRecognizer];
        
    }
    return self;
}

- (void)handleGesture:(UIPanGestureRecognizer *)gestureRecognizer
{
    CGPoint point = [gestureRecognizer locationInView:self.superview];
    //point.x -= 36/2;
    //point.y -= 60/2;
    CGRect newFrame = self.frame;
    newFrame.origin.x = point.x;
    newFrame.origin.y = point.y;
    self.frame = newFrame;
    
    CGPoint pointInImage = [gestureRecognizer locationInView:self.imageView];
    //pointInImage.x -= 36/2;
    //pointInImage.y -= 60/2;
    [self.imageView getColorOfPoint:pointInImage];
}
                                                
                                                 
                                                 

/*
// Only override drawRect: if you perform custom drawing.
// An empty implementation adversely affects performance during animation.
- (void)drawRect:(CGRect)rect
{
    // Drawing code
}
*/

@end
