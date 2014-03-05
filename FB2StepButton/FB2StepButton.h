//
//  FBButton.h
//  clearButton
//
//  Created by Fernando Bass on 9/11/13.
//  Copyright (c) 2013 Fernando Bass. All rights reserved.
//

#import <UIKit/UIKit.h>

typedef enum
{
    FB2StepButtonStepTap,
    FBButtonActionClear
} FB2StepButtonStep;

typedef enum
{
    FB2StepButtonSlideLeft,
    FB2StepButtonSlideRight
} FB2StepButtonSlide;

@protocol FB2StepButtonDelegate <NSObject>
- (void)clickedButtonWithAction:(FB2StepButtonStep)step sender:(id)sender;
@end

@interface FB2StepButton : UIView
- (id)initWithDelegate:(id <FB2StepButtonDelegate>)delegate position:(CGPoint)position;
- (void)resetButton;
@property (strong) id<FB2StepButtonDelegate> delegate;
@property (nonatomic) BOOL isClear;
@property (nonatomic) FB2StepButtonSlide slide;
@end
