//
//  ColorImageView.h
//  ColorPicker
//
//  Created by Mango on 14-2-11.
//  Copyright (c) 2014年 Mango. All rights reserved.
//

#import <UIKit/UIKit.h>

@interface ColorImageView : UIImageView

@property (strong, nonatomic) UIColor *selectedColor;
@property (strong, nonatomic) NSString *red;
@property (strong, nonatomic) NSString *green;
@property (strong, nonatomic) NSString *blue;
@property (strong, nonatomic) NSString *hexRGB;
@property (strong, nonatomic) UIImageView *colorPickerView;


- (void) getColorOfPoint:(CGPoint)point;

@end