//
//  ColorScrollView.h
//  ColorPicker
//
//  Created by Mango on 14-2-11.
//  Copyright (c) 2014年 Mango. All rights reserved.
//

#import <UIKit/UIKit.h>
@class ColorImageView;


@protocol ColorDetectViewDelegate <UIScrollViewDelegate>

@optional
- (void)handelColor:(NSString*)hexColor;

@end


@interface ColorDetectView : UIScrollView

@property (weak,nonatomic) id<ColorDetectViewDelegate> delegate;

@property (strong,readonly,nonatomic) UIImageView *imageView;
@property (nonatomic, readonly) BOOL hasSelectedPoint;
@property (nonatomic, readonly) CGPoint selectedNormalizedPoint;
/// Both gestures and Sample Center use this path, keeping marker/readout on one image pixel.
- (BOOL)sampleAtImagePoint:(CGPoint)point;
- (BOOL)sampleVisibleCenter;
- (instancetype)initWithFrame:(CGRect)frame andUIImage:(UIImage*)image;


@end
