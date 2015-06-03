//
//  ColorImageView.h
//  ColorPicker
//
//  Created by Mango on 14-2-11.
//  Copyright (c) 2014年 Mango. All rights reserved.
//

#import <UIKit/UIKit.h>

@protocol ColorImageViewDelegate <NSObject>

@optional
- (void)handelColor:(NSString*)hexColor;
@end

@interface ColorImageView : UIImageView


@property (nonatomic,weak)  id<ColorImageViewDelegate>delegate;

@end