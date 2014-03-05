//
//  FBButton.m
//  clearButton
//
//  Created by Fernando Bass on 9/11/13.
//  Copyright (c) 2013 Fernando Bass. All rights reserved.
//

#import "FB2StepButton.h"
#import <QuartzCore/QuartzCore.h>

@interface FB2StepButton ()
@property (strong) UIButton *mainButton;
@property (strong) UIButton *clearButton;
- (void)setupButtons;
- (void)setupView;
- (void)buttonAction:(id)sender;
@end

@implementation FB2StepButton

- (id)initWithFrame:(CGRect)frame
{
    self = [super initWithFrame:frame];
    if (self) {
        [self setupView];
        [self setupButtons];
    }
    return self;
}

- (id)initWithDelegate:(id <FB2StepButtonDelegate>)delegate position:(CGPoint)position
{
    if (delegate && [delegate conformsToProtocol:@protocol(FB2StepButtonDelegate)]) {
        _delegate = delegate;
        _slide = FB2StepButtonSlideLeft;
        return (self = [self initWithFrame:CGRectMake(position.x, position.y, 18, 18)]);
    }
    
    return self;
}

- (void)setupButtons
{
    self.mainButton = [[UIButton alloc ] initWithFrame:CGRectMake(1, 0, self.frame.size.width, self.frame.size.height)];
    [self.mainButton setTitleColor:[UIColor lightGrayColor] forState:UIControlStateNormal];
    [self.mainButton setTitle:@"X" forState:UIControlStateNormal];
    self.mainButton.titleLabel.font = [UIFont fontWithName:@"HelveticaNeue-Bold" size:12];
    [self.mainButton addTarget:self action:@selector(buttonAction:) forControlEvents:UIControlEventTouchUpInside];
    self.mainButton.layer.cornerRadius = self.frame.size.width / 2.0;
    [self addSubview:self.mainButton];
    
    
    self.clearButton = [[UIButton alloc ] initWithFrame:CGRectMake(0, 0, self.frame.size.width, self.frame.size.height)];
    [self.clearButton setTitleColor:[UIColor lightGrayColor] forState:UIControlStateNormal];
    self.clearButton.titleLabel.font = [UIFont fontWithName:@"HelveticaNeue-Bold" size:12];
    [self.clearButton setTitle:@"保存" forState:UIControlStateNormal];
    [self.clearButton addTarget:self action:@selector(buttonAction:) forControlEvents:UIControlEventTouchUpInside];
    self.clearButton.layer.cornerRadius = self.frame.size.width / 2.0;
    self.clearButton.alpha = 0;
    [self.clearButton setReversesTitleShadowWhenHighlighted:YES];
    [self addSubview:self.clearButton];
    
}

- (void)setupView
{
    self.backgroundColor = [UIColor colorWithRed:0.159 green:0.116 blue:0.121 alpha:1.000];
    self.userInteractionEnabled = YES;
    self.layer.borderColor = [UIColor blackColor].CGColor;
    self.layer.borderWidth = .2;
    self.layer.cornerRadius = self.frame.size.width / 2.0;
}

- (void)buttonAction:(id)sender
{
    __block CGRect frame = self.frame;
    __block CGSize size = [self.clearButton.titleLabel.text sizeWithFont:[UIFont fontWithName:@"HelveticaNeue-Bold" size:12]];
    if (self.isClear) {
        self.isClear = NO;
        [_delegate clickedButtonWithAction:FBButtonActionClear sender:self];
    }else{
        [UIView animateWithDuration:.3 animations:^{
            frame.size.width = 50;
            if (_slide == FB2StepButtonSlideLeft) {
                frame.origin.x = frame.origin.x - size.width;
            }
            self.frame = frame;
            self.mainButton.transform = CGAffineTransformMakeRotation(180 * M_PI / 180);
            self.mainButton.alpha = 0;
            self.clearButton.frame = CGRectMake(0, 0, self.frame.size.width, self.frame.size.height);
            [_delegate clickedButtonWithAction:FB2StepButtonStepTap sender:self];
        }completion:^(BOOL finished) {
            self.clearButton.alpha = 1;
        }];
        self.isClear = YES;
    }
}

- (void)resetButton
{
    __block CGRect frame = self.frame;
    __block CGSize size = [self.clearButton.titleLabel.text sizeWithFont:[UIFont fontWithName:@"HelveticaNeue-Bold" size:12]];
    [UIView animateWithDuration:.3 animations:^{
        frame.size.width = frame.size.height;
        if (_slide == FB2StepButtonSlideLeft) {
            frame.origin.x = frame.origin.x + size.width;
        }
        self.frame = frame;
        self.clearButton.frame = CGRectMake(0, 0, self.frame.size.width, self.frame.size.height);
        self.clearButton.alpha = 0;
        self.mainButton.transform = CGAffineTransformMakeRotation(0);
        self.mainButton.alpha = 1;
        [_delegate clickedButtonWithAction:FBButtonActionClear sender:self];
    }];
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
