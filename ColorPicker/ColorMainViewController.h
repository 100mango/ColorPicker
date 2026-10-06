//
//  ColorMainViewController.h
//  ColorPicker
//
//  Created by Mango on 15/1/16.
//  Copyright (c) 2015年 Mango. All rights reserved.
//

#import <UIKit/UIKit.h>

@class ColorMainViewController;
@protocol TCColorWorkspaceDelegate <NSObject>
- (UIViewController *)sourcePresenterForPalette:(ColorMainViewController *)palette;
- (UIBarButtonItem *)sourceAnchorForPalette:(ColorMainViewController *)palette;
- (void)palette:(ColorMainViewController *)palette showCanvas:(UIViewController *)canvas;
- (void)palette:(ColorMainViewController *)palette sourceFlowActive:(BOOL)active;
- (void)palette:(ColorMainViewController *)palette loadingPhoto:(BOOL)loading;
- (void)palette:(ColorMainViewController *)palette previewSavedColor:(NSString *)hex;
@end

@interface ColorMainViewController : UIViewController
@property (nonatomic, weak) id<TCColorWorkspaceDelegate> workspaceDelegate;
- (void)choosePhoto;
- (void)cancelPhotoImport;
- (void)takePhoto;
- (void)openLiveColor;
- (void)openPrivacyPolicy;
- (void)openPaletteImport;
@end
