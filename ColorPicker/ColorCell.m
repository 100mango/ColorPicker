//
//  ColorCell.m
//  ColorPicker
//
//  Created by Mango on 14-3-4.
//  Copyright (c) 2014年 Mango. All rights reserved.
//

#import "ColorCell.h"

@interface ColorCell ()

@property (strong,nonatomic) UILabel *red;
@property (strong,nonatomic) UILabel *green;
@property (strong,nonatomic) UILabel *blue;
@property (strong,nonatomic) UILabel *hexRGB;
@property (strong,nonatomic) UIImageView *selectedColoImageView;

@end

@implementation ColorCell

- (id)initWithStyle:(UITableViewCellStyle)style reuseIdentifier:(NSString *)reuseIdentifier
{
    self = [super initWithStyle:style reuseIdentifier:reuseIdentifier];
    if (self)
    {
        //初始化背景
        UIImageView * backgroudImage = [[UIImageView alloc]initWithImage:[UIImage imageNamed:@"列表.png"]];
        [self setBackgroundView:backgroudImage];
        self.backgroundColor = [UIColor colorWithRed:255/255.0 green:59/255.0 blue:48/255.0 alpha:1];
        //定义选中样式
        self.selectionStyle = UITableViewCellSelectionStyleNone;
        
        //初始化label;
        _red = [[UILabel alloc]initWithFrame:CGRectMake(264/2, 30/2 -2, 30, 20)];
        _green = [[UILabel alloc]initWithFrame:CGRectMake(264/2, 70/2 -2, 30, 20)];
        _blue = [[UILabel alloc]initWithFrame:CGRectMake(264/2, 110/2 -2, 30, 20)];
        _hexRGB= [[UILabel alloc]initWithFrame:CGRectMake(438/2, 72/2 - 4, 80, 20)];
        
        self.red.font = [UIFont systemFontOfSize:12.0];
        self.green.font = [UIFont systemFontOfSize:12.0];
        self.blue.font = [UIFont systemFontOfSize:12.0];
        self.hexRGB.font = [UIFont systemFontOfSize:12.0];
        self.red.textColor = [UIColor colorWithRed:76.0/255 green:103.0/255 blue:122.0/255 alpha:1.0];
        self.green.textColor = [UIColor colorWithRed:76.0/255 green:103.0/255 blue:122.0/255 alpha:1.0];
        self.blue.textColor = [UIColor colorWithRed:76.0/255 green:103.0/255 blue:122.0/255 alpha:1.0];
        self.hexRGB.textColor = self.red.textColor = [UIColor colorWithRed:76.0/255 green:103.0/255 blue:122.0/255 alpha:1.0];

        [self addSubview:self.red];
        [self addSubview:self.green];
        [self addSubview:self.blue];
        [self addSubview:self.hexRGB];
        
        //初始化显示色彩图片
        _selectedColoImageView = [[UIImageView alloc]initWithFrame:CGRectMake(42/2, 24/2, 126/2, 126/2)];
        self.selectedColoImageView.image = [UIImage imageNamed:@"42x793"];
        [self addSubview:self.selectedColoImageView];
        
    }
    return self;
}

- (void)setSelected:(BOOL)selected animated:(BOOL)animated
{
    [super setSelected:selected animated:animated];

    // Configure the view for the selected state
}

//设置颜色信息
- (void)setColorInformationWith:(NSString*)hexColor
{
    //转换hex值
    unsigned int red ,green,blue;

    NSScanner *scanner = [NSScanner scannerWithString:[hexColor substringWithRange:NSMakeRange(1, 2)]];
    [scanner scanHexInt:&red];
    NSLog(@"%d",red);
    
    scanner = [NSScanner scannerWithString:[hexColor substringWithRange:NSMakeRange(3, 2)]];
    [scanner scanHexInt:&green];
    
    scanner = [NSScanner scannerWithString:[hexColor substringWithRange:NSMakeRange(5, 2)]];
    [scanner scanHexInt:&blue];
    
    
    self.red.text = [NSString stringWithFormat:@"%d",red];
    self.green.text = [NSString stringWithFormat:@"%d",green];
    self.blue.text = [NSString stringWithFormat:@"%d",blue];
    self.hexRGB.text = hexColor;
    
    self.selectedColoImageView.backgroundColor = [UIColor colorWithRed:red/255.0 green:green/255.0 blue:blue/255.0 alpha:1];
}

@end
