//
//  ColorRealTimeViewController.h
//  ColorPicker
//
//  Created by Mango on 14-2-11.
//  Copyright (c) 2014年 Mango. All rights reserved.
//

#import <UIKit/UIKit.h>
#import <AVFoundation/AVFoundation.h>
@interface ColorRealTimeViewController : UIViewController<AVCaptureVideoDataOutputSampleBufferDelegate>
/// A source popover can cover only part of the canvas; explicitly suspend capture until it closes.
@property (nonatomic) BOOL sourceFlowActive;
@end
