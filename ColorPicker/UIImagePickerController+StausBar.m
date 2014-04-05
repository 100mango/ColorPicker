//
//  UIImagePickerController+StausBar.m
//  ColorPicker
//
//  Created by Mango on 14-4-3.
//  Copyright (c) 2014年 Mango. All rights reserved.
//

#import "UIImagePickerController+StausBar.h"

@implementation UIImagePickerController (StausBar)

-(BOOL)prefersStatusBarHidden
{
    return YES;
}

- (UIViewController *)childViewControllerForStatusBarHidden
{
    return nil;
}

@end
