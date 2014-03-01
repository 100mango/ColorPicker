//
//  ColorEntranceViewController.m
//  ColorPicker
//
//  Created by Mango on 14-2-11.
//  Copyright (c) 2014年 Mango. All rights reserved.
//

#import "ColorEntranceViewController.h"
#import "ColorViewController.h"
#import "ColorScrollView.h"
#import "ColorRealTimeViewController.h"

//使用hex颜色的宏
#define UIColorFromRGB(rgbValue) [UIColor colorWithRed:((float)((rgbValue & 0xFF0000) >> 16))/255.0 green:((float)((rgbValue & 0xFF00) >> 8))/255.0 blue:((float)(rgbValue & 0xFF))/255.0 alpha:1.0]
//按钮尺寸
#define SELECT_PHOTO_BUTTON_FRAME CGRectMake(117/2, 532/2, 406/2, 102/2)
#define PICK_PHOTO_BUTTON_FRAME CGRectMake(117/2, 638/2, 406/2, 102/2)
#define REAL_TIME_BUTTON_FRAME CGRectMake(117/2, 744/2, 406/2, 102/2)
#define TOP_SELECT_STATE_BUTTON_FRAME CGRectMake(112/2, 138/2, 208/2, 36/2)
#define TOP_COLOR_LIBRARY_STATE_FRAME CGRectMake(320/2, 138/2, 208/2, 36/2)

@interface ColorEntranceViewController ()
@property (strong,nonatomic) UIButton *selectPhotoButton;
@property (strong,nonatomic) UIButton *pickPhotoButton;
@property (strong,nonatomic) UIButton *realTimeButton;
@property (strong,nonatomic) UIButton *topSelectStateButton;
@property (strong,nonatomic) UIButton *topColorLibrayStateButton;
@end

@implementation ColorEntranceViewController

- (id)initWithNibName:(NSString *)nibNameOrNil bundle:(NSBundle *)nibBundleOrNil
{
    self = [super initWithNibName:nibNameOrNil bundle:nibBundleOrNil];
    if (self) {
        // Custom initialization
    }
    return self;
}

//设置状态栏
-(UIStatusBarStyle)preferredStatusBarStyle
{
    return UIStatusBarStyleLightContent;
}

- (void)viewDidLoad
{
    [super viewDidLoad];
    
    //设置NavigationBar
    self.navigationBar.hidden = YES;
    
    //设置自定义导航条背景
    UIImageView *topButtonBackGroud = [[UIImageView alloc]initWithFrame:CGRectMake(0, 0, 320, 192/2)];
    topButtonBackGroud.image = [UIImage imageNamed:@"00.png"];
    [self.view addSubview:topButtonBackGroud];
    
    //设置导航条按钮
    
    
    //设置背景
    self.view.backgroundColor = [UIColor colorWithRed:239.0/255.0 green:239.0/255.0 blue:237.0/255.0 alpha:1];
    UIImageView *imageView = [[UIImageView alloc]initWithFrame:CGRectMake(240/2, 248/2, 160/2, 228/2)];
    imageView.image = [UIImage imageNamed:@"240x248.png"];
    [self.view addSubview:imageView];
    
    /**
     *  初始化按钮
     */
    _selectPhotoButton = [UIButton buttonWithType:UIButtonTypeCustom];
    self.selectPhotoButton.frame = SELECT_PHOTO_BUTTON_FRAME;
    [self.selectPhotoButton setBackgroundImage:[UIImage imageNamed:@"117x532.png"] forState:UIControlStateNormal];
    [self.selectPhotoButton setBackgroundImage:[UIImage imageNamed:@"117x532 B.png"] forState:UIControlStateHighlighted];
    [self.selectPhotoButton addTarget:self action:@selector(selectImage) forControlEvents:UIControlEventTouchUpInside];
    [self.view addSubview:self.selectPhotoButton];
    
    
    _pickPhotoButton = [UIButton buttonWithType:UIButtonTypeCustom];
    self.pickPhotoButton.frame = PICK_PHOTO_BUTTON_FRAME;
    [self.pickPhotoButton setBackgroundImage:[UIImage imageNamed:@"117x638.png"] forState:UIControlStateNormal];
    [self.pickPhotoButton setBackgroundImage:[UIImage imageNamed:@"117x638 B.png"] forState:UIControlStateHighlighted];
    [self.pickPhotoButton addTarget:self action:@selector(pickImage) forControlEvents:UIControlEventTouchUpInside];
    [self.view addSubview:self.pickPhotoButton];
    
    _realTimeButton = [UIButton buttonWithType:UIButtonTypeCustom];
    self.realTimeButton.frame = REAL_TIME_BUTTON_FRAME;
    [self.realTimeButton setBackgroundImage:[UIImage imageNamed:@"117x744.png"] forState:UIControlStateNormal];
    [self.realTimeButton setBackgroundImage:[UIImage imageNamed:@"117x744 B.png"] forState:UIControlStateHighlighted];
    [self.realTimeButton addTarget:self action:@selector(realTimeView) forControlEvents:UIControlEventTouchUpInside];
    [self.view addSubview:self.realTimeButton];
    
    _topSelectStateButton = [UIButton buttonWithType:UIButtonTypeCustom];
    self.topSelectStateButton.frame = TOP_SELECT_STATE_BUTTON_FRAME;
    [self.topSelectStateButton setBackgroundImage:[UIImage imageNamed:@"112x138 B.png"] forState:UIControlStateNormal];
    [self.topSelectStateButton setBackgroundImage:[UIImage imageNamed:@"112x138.png"] forState:UIControlStateHighlighted];
    [self.view addSubview:self.topSelectStateButton];
    
    _topColorLibrayStateButton = [UIButton buttonWithType:UIButtonTypeCustom];
    self.topColorLibrayStateButton.frame = TOP_COLOR_LIBRARY_STATE_FRAME;
    [self.topColorLibrayStateButton setBackgroundImage:[UIImage imageNamed:@"320x138.png"] forState:UIControlStateNormal];
    [self.topColorLibrayStateButton setBackgroundImage:[UIImage imageNamed:@"320x138 B.png"] forState:UIControlStateHighlighted];
    [self.view addSubview:self.topColorLibrayStateButton];
}

- (void)didReceiveMemoryWarning
{
    [super didReceiveMemoryWarning];
    // Dispose of any resources that can be recreated.
}
#pragma mark -buttonMethod

- (void)selectImage
{
    //检查有无照相机
    if ([UIImagePickerController isSourceTypeAvailable:UIImagePickerControllerSourceTypePhotoLibrary] == NO
        )
    {
        UIAlertView * alert = [[UIAlertView alloc]initWithTitle:@"无本地相册" message:Nil delegate:nil cancelButtonTitle:@"YES" otherButtonTitles:nil, nil];
        [alert show];
    }
    
    //_imagePicker = [[UIImagePickerController alloc]init];
    //self.imagePicker.sourceType = UIImagePickerControllerSourceTypePhotoLibrary;
    //self.imagePicker.delegate = self;
    
    UIImagePickerController *imageLibray = [[UIImagePickerController alloc]init];
    imageLibray.sourceType = UIImagePickerControllerSourceTypePhotoLibrary;
    imageLibray.delegate = self;
    
    //按钮被激发的动画
    [UIView animateWithDuration: 0.7
                     animations:
     ^{
         self.selectPhotoButton.frame = CGRectMake(117/2 + 400, 532/2, 406/2, 102/2);
         self.selectPhotoButton.alpha = 0.0;
      }
                     completion:
     ^(BOOL finished){
         [self presentViewController:imageLibray animated:YES completion:
          ^{
              self.selectPhotoButton.frame = SELECT_PHOTO_BUTTON_FRAME;
              self.selectPhotoButton.alpha = 1;

          }];
     }];
    
}

- (void)pickImage
{
    //检查有无摄像头
    if ([UIImagePickerController isSourceTypeAvailable:UIImagePickerControllerSourceTypeCamera] == NO
        )
    {
        UIAlertView * alert = [[UIAlertView alloc]initWithTitle:@"无照相机" message:Nil delegate:nil cancelButtonTitle:@"YES" otherButtonTitles:nil, nil];
        [alert show];
    }
    
    UIImagePickerController *imagePicker = [[UIImagePickerController alloc]init];
    imagePicker.sourceType = UIImagePickerControllerSourceTypeCamera;
    imagePicker.delegate = self;
    
    //按钮被激活动画
    [UIView animateWithDuration: 0.7
                     animations:
     ^{
         self.pickPhotoButton.frame = CGRectMake(117/2 + 400, 638/2, 406/2, 102/2);
         self.pickPhotoButton.alpha = 0.0;
     }
                     completion:
     ^(BOOL finished){
         [self presentViewController:imagePicker animated:YES completion:
          ^{
              self.pickPhotoButton.frame = PICK_PHOTO_BUTTON_FRAME;
              self.pickPhotoButton.alpha = 1;
              
          }];
     }];
    //[self presentViewController:imagePicker animated:YES completion:nil];
}

- (void)realTimeView
{
    ColorRealTimeViewController *realTimeController = [[ColorRealTimeViewController alloc]init];
    [self presentViewController:realTimeController animated:YES completion:nil];
}

#pragma mark -imagePicker

- (void)imagePickerController:(UIImagePickerController *)picker didFinishPickingMediaWithInfo:(NSDictionary *)info
{
    UIImage *image = [info objectForKey:UIImagePickerControllerOriginalImage];
    ColorViewController *colorViewController = [[ColorViewController alloc]initWithImage:image];
    [picker presentViewController:colorViewController animated:YES completion:nil];
    //[picker dismissViewControllerAnimated:NO completion:nil];

}

@end
