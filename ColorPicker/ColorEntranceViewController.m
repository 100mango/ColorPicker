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
#import "ColorCell.h"


//适配iphone
#define DEVICE_IS_IPHONE5 ([[UIScreen mainScreen] bounds].size.height == 568)

//按钮尺寸
#define SELECT_PHOTO_BUTTON_FRAME CGRectMake(117/2, 532/2, 406/2, 102/2)
#define PICK_PHOTO_BUTTON_FRAME CGRectMake(117/2, 638/2, 406/2, 102/2)
#define REAL_TIME_BUTTON_FRAME CGRectMake(117/2, 744/2, 406/2, 102/2)
#define TOP_SELECT_STATE_BUTTON_FRAME CGRectMake(112/2, 138/2, 208/2, 36/2)
#define TOP_COLOR_LIBRARY_STATE_FRAME CGRectMake(320/2, 138/2, 208/2, 36/2)
//iphone5
#define SELECT_PHOTO_BUTTON_FRAME_IPHONE5 CGRectMake(117/2, 642/2, 406/2, 102/2)
#define PICK_PHOTO_BUTTON_FRAME_IPHONE5 CGRectMake(117/2, 748/2, 406/2, 102/2)
#define REAL_TIME_BUTTON_FRAME_IPHONE5 CGRectMake(117/2, 854/2, 406/2, 102/2)

@interface ColorEntranceViewController ()

@property (strong,nonatomic) UIButton *selectPhotoButton;
@property (strong,nonatomic) UIButton *pickPhotoButton;
@property (strong,nonatomic) UIButton *realTimeButton;
@property (strong,nonatomic) UIButton *topEntranceViewButton;
@property (strong,nonatomic) UIButton *topColorLibrayStateButton;
@property (strong,nonatomic) UITableView *tableView;
@property (strong,nonatomic) NSMutableArray *colorArray;

@end

@implementation ColorEntranceViewController

//设置状态栏
-(UIStatusBarStyle)preferredStatusBarStyle
{
    return UIStatusBarStyleLightContent;
}

- (void)viewDidLoad
{
    [super viewDidLoad];
    
    //[self setupNavigationBar];
    //[self setupBackground];
    //[self setupButtons];
}

- (void)didReceiveMemoryWarning
{
    [super didReceiveMemoryWarning];
    // Dispose of any resources that can be recreated.
}


#pragma mark -setupView

- (void)setupNavigationBar
{
    //设置NavigationBar
    self.navigationBar.hidden = YES;
    
    //设置自定义导航条背景
    UIImageView *topButtonBackGroud = [[UIImageView alloc]initWithFrame:CGRectMake(0, 0, 320, 192/2)];
    topButtonBackGroud.image = [UIImage imageNamed:@"00.png"];
    [self.view addSubview:topButtonBackGroud];
    
    //设置导航条按钮
    _topEntranceViewButton = [UIButton buttonWithType:UIButtonTypeCustom];
    self.topEntranceViewButton.frame = TOP_SELECT_STATE_BUTTON_FRAME;
    [self.topEntranceViewButton addTarget:self action:@selector(showEntranceView) forControlEvents:UIControlEventTouchUpInside];
    self.topEntranceViewButton.selected = YES;
    [self.topEntranceViewButton setBackgroundImage:[UIImage imageNamed:@"112x138.png"] forState:UIControlStateNormal];
    [self.topEntranceViewButton setBackgroundImage:[UIImage imageNamed:@"112x138 B.png"] forState:UIControlStateHighlighted];
    [self.topEntranceViewButton setBackgroundImage:[UIImage imageNamed:@"112x138 B.png"] forState:UIControlStateSelected];
    [self.view addSubview:self.topEntranceViewButton];
    
    _topColorLibrayStateButton = [UIButton buttonWithType:UIButtonTypeCustom];
    self.topColorLibrayStateButton.frame = TOP_COLOR_LIBRARY_STATE_FRAME;
    [self.topColorLibrayStateButton addTarget:self action:@selector(showColorRecord) forControlEvents:UIControlEventTouchUpInside];
    [self.topColorLibrayStateButton setImage:[UIImage imageNamed:@"320x138.png"] forState:UIControlStateNormal];
    [self.topColorLibrayStateButton setImage:[UIImage imageNamed:@"320x138 B.png"] forState:UIControlStateSelected];
    [self.topColorLibrayStateButton setImage:[UIImage imageNamed:@"320x138 B.png"] forState:UIControlStateHighlighted];
    //出现了问题 为什么直接使用 uicontrolStateHighlighted|uicontrolStareSelected不行
    [self.view addSubview:self.topColorLibrayStateButton];
}

- (void)setupBackground
{
    //设置背景
    self.view.backgroundColor = [UIColor colorWithRed:239.0/255.0 green:239.0/255.0 blue:237.0/255.0 alpha:1];
    UIImageView *imageView = nil;
    if (DEVICE_IS_IPHONE5)
    {
        imageView = [[UIImageView alloc]initWithFrame:CGRectMake(245/2, 310/2, 151/2, 230/2)];
    }
    else
    {
        imageView = [[UIImageView alloc]initWithFrame:CGRectMake(245/2, 248/2, 151/2, 230/2)];
    }
    imageView.image = [UIImage imageNamed:@"245x248"];
    [self.view addSubview:imageView];
}

- (void)setupButtons
{
    _selectPhotoButton = [UIButton buttonWithType:UIButtonTypeCustom];
    if (DEVICE_IS_IPHONE5) {
        self.selectPhotoButton.frame = SELECT_PHOTO_BUTTON_FRAME_IPHONE5;
    }
    else
    {
        self.selectPhotoButton.frame = SELECT_PHOTO_BUTTON_FRAME;

    }
    [self.selectPhotoButton setBackgroundImage:[UIImage imageNamed:@"117x532.png"] forState:UIControlStateNormal];
    [self.selectPhotoButton setBackgroundImage:[UIImage imageNamed:@"117x532 B.png"] forState:UIControlStateHighlighted];
    [self.selectPhotoButton addTarget:self action:@selector(selectImage) forControlEvents:UIControlEventTouchUpInside];
    [self.view addSubview:self.selectPhotoButton];
    
    
    _pickPhotoButton = [UIButton buttonWithType:UIButtonTypeCustom];
    if (DEVICE_IS_IPHONE5) {
        self.pickPhotoButton.frame = PICK_PHOTO_BUTTON_FRAME_IPHONE5;
    }
    else
    {
        self.pickPhotoButton.frame = PICK_PHOTO_BUTTON_FRAME;
    }
    [self.pickPhotoButton setBackgroundImage:[UIImage imageNamed:@"117x638.png"] forState:UIControlStateNormal];
    [self.pickPhotoButton setBackgroundImage:[UIImage imageNamed:@"117x638 B.png"] forState:UIControlStateHighlighted];
    [self.pickPhotoButton addTarget:self action:@selector(pickImage) forControlEvents:UIControlEventTouchUpInside];
    [self.view addSubview:self.pickPhotoButton];
    
    _realTimeButton = [UIButton buttonWithType:UIButtonTypeCustom];
    if (DEVICE_IS_IPHONE5) {
        self.realTimeButton.frame = REAL_TIME_BUTTON_FRAME_IPHONE5;
    }
    else
    {
        self.realTimeButton.frame = REAL_TIME_BUTTON_FRAME;
    }
    [self.realTimeButton setBackgroundImage:[UIImage imageNamed:@"117x744.png"] forState:UIControlStateNormal];
    [self.realTimeButton setBackgroundImage:[UIImage imageNamed:@"117x744 B.png"] forState:UIControlStateSelected|UIControlStateHighlighted];
    [self.realTimeButton addTarget:self action:@selector(realTimeView) forControlEvents:UIControlEventTouchUpInside];
    [self.view addSubview:self.realTimeButton];
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
    
    UIImagePickerController *imageLibray = [[UIImagePickerController alloc]init];
    imageLibray.sourceType = UIImagePickerControllerSourceTypePhotoLibrary;
    imageLibray.delegate = self;
    //定制选择图片时的的navigationBar外观
    imageLibray.navigationBar.barTintColor = [UIColor colorWithRed:55/255.0 green:55/255.0 blue:54/255.0 alpha:1];
    imageLibray.navigationBar.tintColor = [UIColor whiteColor];
    imageLibray.navigationBar.translucent = NO;
    imageLibray.navigationBar.titleTextAttributes = @{NSForegroundColorAttributeName: [UIColor whiteColor]};
    [imageLibray setNeedsStatusBarAppearanceUpdate];
    
    //按钮被激发的动画
    [UIView animateWithDuration: 0.3
                     animations:
     ^{
         self.selectPhotoButton.alpha = 0.0;
      }
                     completion:
     ^(BOOL finished){
         [self presentViewController:imageLibray animated:YES completion:
          ^{
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
    [UIView animateWithDuration: 0.3
                     animations:
     ^{
         self.pickPhotoButton.alpha = 0.0;
     }
                     completion:
     ^(BOOL finished){
         [self presentViewController:imagePicker animated:YES completion:
          ^{
              self.pickPhotoButton.alpha = 1;
              
          }];
     }];
}

- (void)realTimeView
{
    ColorRealTimeViewController *realTimeController = [[ColorRealTimeViewController alloc]init];
    [self presentViewController:realTimeController animated:YES completion:nil];
}

- (void)showColorRecord
{
    //设置按钮选中状态
    self.topEntranceViewButton.selected = NO;
    self.topColorLibrayStateButton.selected = YES;
    
    //取tableview要显示的数据
    NSUserDefaults * defaults = [NSUserDefaults standardUserDefaults];
    self.colorArray = [[defaults arrayForKey:@"colorArray"] mutableCopy];
    for (NSString * string in self.colorArray)
    {
        NSLog(@"%@",string);
    }
    
    //显示tableView lazy init
    if (_tableView == nil)
    {
        if (DEVICE_IS_IPHONE5) {
            _tableView = [[UITableView alloc]initWithFrame:CGRectMake(0, 192/2, 320, 568 - 192/2)];

        }
        else
        {
            _tableView = [[UITableView alloc]initWithFrame:CGRectMake(0, 192/2, 320, 480 - 192/2)];
        }
        self.tableView.backgroundColor = [UIColor whiteColor];
        self.tableView.separatorStyle = UITableViewCellSeparatorStyleNone;
        
        self.tableView.delegate = self;
        self.tableView.dataSource = self;
        [self.view addSubview:self.tableView];
    }
    else
    {
        [self.tableView reloadData];
        self.tableView.hidden = NO;
    }
}

- (void)showEntranceView
{
    self.tableView.hidden = YES;
    self.topColorLibrayStateButton.selected = NO;
    self.topEntranceViewButton.selected = YES;
}


#pragma mark -imagePicker delegate

- (void)imagePickerController:(UIImagePickerController *)picker didFinishPickingMediaWithInfo:(NSDictionary *)info
{
    UIImage *image = [info objectForKey:UIImagePickerControllerOriginalImage];
    ColorViewController *colorViewController = [[ColorViewController alloc]init];
    [picker presentViewController:colorViewController animated:YES completion:nil];
    [colorViewController setChooseImage:image];
}

#pragma mark -tableView datasource

-(UITableViewCell *)tableView:(UITableView *)tableView cellForRowAtIndexPath:(NSIndexPath *)indexPath
{
    NSString *cellIdentifier = @"colorCell" ;
    ColorCell *cell = [tableView dequeueReusableCellWithIdentifier:cellIdentifier];
    
    if (cell == nil)
    {
        cell = [[ColorCell alloc]initWithStyle:UITableViewCellStyleDefault reuseIdentifier:cellIdentifier];
    }
    
    //设置cell属性
    [cell setColorInformationWith:[self.colorArray objectAtIndex:indexPath.row]];
    return cell;
}

-(NSInteger)tableView:(UITableView *)tableView numberOfRowsInSection:(NSInteger)section
{
    //返回需要显示的行数
    return [self.colorArray count];
}


//删除选择列，更新颜色值数组
- (void)tableView:(UITableView *)tableView commitEditingStyle:(UITableViewCellEditingStyle)editingStyle forRowAtIndexPath:(NSIndexPath *)indexPath
{
    
    [self.colorArray removeObjectAtIndex:indexPath.row];
    
    //保存进本地
    NSUserDefaults * userDefault = [NSUserDefaults standardUserDefaults];
    [userDefault setObject:self.colorArray forKey:@"colorArray"];
    [userDefault synchronize];
    
    [tableView deleteRowsAtIndexPaths:[NSArray arrayWithObject:indexPath] withRowAnimation:UITableViewRowAnimationAutomatic];
}

#pragma mark -tableview delegate

- (CGFloat)tableView:(UITableView *)tableView heightForRowAtIndexPath:(NSIndexPath *)indexPath
{
    return 170/2;
}

// 返回cell editing的样式
- (UITableViewCellEditingStyle)tableView:(UITableView *)tableView editingStyleForRowAtIndexPath:(NSIndexPath *)indexPath
{
    return UITableViewCellEditingStyleDelete;
}


@end
