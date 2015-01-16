//
//  ColorMainViewController.m
//  ColorPicker
//
//  Created by Mango on 15/1/16.
//  Copyright (c) 2015年 Mango. All rights reserved.
//

#import "ColorMainViewController.h"

//controller
#import "ColorViewController.h"
@interface ColorMainViewController ()<UIImagePickerControllerDelegate,UINavigationControllerDelegate>

@end

@implementation ColorMainViewController

- (void)viewDidLoad {
    [super viewDidLoad];
    
    //setup view
    [self setupNavigationBar];
    
}

- (void)didReceiveMemoryWarning {
    [super didReceiveMemoryWarning];
    // Dispose of any resources that can be recreated.
}


#pragma mark -setup view
- (void)setupNavigationBar
{
    self.title = @"Touch Color";
    self.navigationController.navigationBar.tintColor = [UIColor whiteColor];
    [self.navigationController.navigationBar setTranslucent:NO];
    //隐藏细线
    [self.navigationController.navigationBar setShadowImage:[UIImage imageNamed:@"TransparentPixel"]];
    [self.navigationController.navigationBar setBackgroundImage:[UIImage new] forBarMetrics:UIBarMetricsDefault];

    self.navigationController.navigationBar.barTintColor = [UIColor colorWithRed:55/255.0 green:55/255.0 blue:44/255.0 alpha:1];
}

#pragma mark - action
- (IBAction)PickImageFromGallery:(id)sender
{
    //检查有无照相机
    if ([UIImagePickerController isSourceTypeAvailable:UIImagePickerControllerSourceTypePhotoLibrary] == NO
        )
    {
        UIAlertView * alert = [[UIAlertView alloc]initWithTitle:@"无本地相册" message:Nil delegate:nil cancelButtonTitle:@"OK" otherButtonTitles:nil, nil];
        [alert show];
    }
    else
    {
        
        UIImagePickerController *imageLibray = [[UIImagePickerController alloc]init];
        imageLibray.sourceType = UIImagePickerControllerSourceTypePhotoLibrary;
        imageLibray.delegate = self;
        //定制选择图片时的的navigationBar外观
        imageLibray.navigationBar.barTintColor = [UIColor colorWithRed:55/255.0 green:55/255.0 blue:54/255.0 alpha:1];
        imageLibray.navigationBar.tintColor = [UIColor whiteColor];
        imageLibray.navigationBar.translucent = NO;
        imageLibray.navigationBar.titleTextAttributes = @{NSForegroundColorAttributeName: [UIColor whiteColor]};
        [imageLibray setNeedsStatusBarAppearanceUpdate];
        
        [self presentViewController:imageLibray animated:YES completion:nil];
    }
}
- (IBAction)pickImageWithCamera:(id)sender
{
    //检查有无摄像头
    if ([UIImagePickerController isSourceTypeAvailable:UIImagePickerControllerSourceTypeCamera] == NO
        )
    {
        UIAlertView * alert = [[UIAlertView alloc]initWithTitle:@"无照相机" message:Nil delegate:nil cancelButtonTitle:@"OK" otherButtonTitles:nil, nil];
        [alert show];
    }
    else
    {
        UIImagePickerController *imagePicker = [[UIImagePickerController alloc]init];
        imagePicker.sourceType = UIImagePickerControllerSourceTypeCamera;
        imagePicker.delegate = self;
        [self presentViewController:imagePicker animated:YES completion:nil];
    }
}

#pragma mark -imagePicker delegate

- (void)imagePickerController:(UIImagePickerController *)picker didFinishPickingMediaWithInfo:(NSDictionary *)info
{
    UIImage *image = [info objectForKey:UIImagePickerControllerOriginalImage];
    ColorViewController *colorViewController = [[ColorViewController alloc]init];
    [colorViewController setChooseImage:image];
    [picker.presentingViewController dismissViewControllerAnimated:NO completion:nil];
    [self performSegueWithIdentifier:@"showColorViewController" sender:self];
}


#pragma mark - Navigation

- (void)prepareForSegue:(UIStoryboardSegue *)segue sender:(id)sender
{
}

@end
