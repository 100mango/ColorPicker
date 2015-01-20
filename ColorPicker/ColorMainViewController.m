//
//  ColorMainViewController.m
//  ColorPicker
//
//  Created by Mango on 15/1/16.
//  Copyright (c) 2015年 Mango. All rights reserved.
//

#import "ColorMainViewController.h"

//view
#import "ColorCell.h"
#import "UIView+Tools.h"

//controller
#import "ColorViewController.h"
@interface ColorMainViewController ()<UIImagePickerControllerDelegate,UINavigationControllerDelegate,UITableViewDelegate,UITableViewDataSource>

@property (weak, nonatomic) IBOutlet UIButton *pickImageFromAlbumButton;
@property (weak, nonatomic) IBOutlet UIButton *pickImageFromCameraButton;
@property (weak, nonatomic) IBOutlet NSLayoutConstraint *pickImageTopConstraint;
@property (weak, nonatomic) IBOutlet UIVisualEffectView *pickImageArea;


//被选中的图片
@property (nonatomic,strong) UIImage *pickImage;
//tableview
@property (weak, nonatomic) IBOutlet UITableView *recordTableView;
@property (strong,nonatomic) NSMutableArray *colorArray;

@end

NSString *showColorViewControllerSegueIdentifier = @"showColorViewController";

@implementation ColorMainViewController

- (void)viewDidLoad {
    [super viewDidLoad];
    
    //setup view
    [self setupNavigationBar];
    
    
}

- (void)viewWillAppear:(BOOL)animated
{
    [super viewWillAppear:animated];
    
    //取数据
    NSUserDefaults * defaults = [NSUserDefaults standardUserDefaults];
    self.colorArray = [[defaults arrayForKey:@"colorArray"] mutableCopy];
    [self.recordTableView reloadData];
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

- (IBAction)segemtedControlValueChanged:(UISegmentedControl *)sender
{
    if (sender.selectedSegmentIndex == 0)
    {
        self.recordTableView.hidden = YES;
        self.pickImageFromAlbumButton.hidden = NO;
        self.pickImageFromCameraButton.hidden = NO;
    }
    else
    {
        self.recordTableView.hidden = NO;
        self.pickImageFromAlbumButton.hidden = YES;
        self.pickImageFromCameraButton.hidden = YES;
    }
}

- (IBAction)pickNewColor:(UIButton *)sender
{
    //裁剪为圆
    [sender ClipSquareViewToRound];
    sender.clipsToBounds = YES;
    
    if (sender.selected == NO)
    {
        sender.selected = YES;
        [sender rotateViewWithAngle:M_PI_4 andDuration:0.3];
        
        self.pickImageTopConstraint.constant = -self.recordTableView.frame.size.height;
        [UIView animateWithDuration:0.3 animations:^{
            [self.view layoutIfNeeded];
        }];
    }
    else
    {
        sender.selected = NO;
        [sender rotateViewWithAngle:-M_PI_4 andDuration:0.3];

        self.pickImageTopConstraint.constant = 0;
        [UIView animateWithDuration:0.3 animations:^{
            [self.view layoutIfNeeded];
        }];
    }
}

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

- (IBAction)realTime:(id)sender {
    

}
#pragma mark -imagePicker delegate

- (void)imagePickerController:(UIImagePickerController *)picker didFinishPickingMediaWithInfo:(NSDictionary *)info
{
    UIImage *image = [info objectForKey:UIImagePickerControllerOriginalImage];
    self.pickImage = image;
    
    [picker.presentingViewController dismissViewControllerAnimated:NO completion:^{
        [self performSegueWithIdentifier:showColorViewControllerSegueIdentifier sender:self];

    }];
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


#pragma mark - Navigation

- (void)prepareForSegue:(UIStoryboardSegue *)segue sender:(id)sender
{
    if ([segue.identifier isEqualToString:showColorViewControllerSegueIdentifier])
    {
        ColorViewController *controller = (ColorViewController*)[segue destinationViewController];
        [controller setChooseImage:self.pickImage];
    }
}

@end
