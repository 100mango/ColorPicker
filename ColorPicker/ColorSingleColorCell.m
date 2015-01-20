//
//  ColorSingleColorCell.m
//  ColorPicker
//
//  Created by Mango on 15/1/20.
//  Copyright (c) 2015年 Mango. All rights reserved.
//

#import "ColorSingleColorCell.h"

@interface ColorSingleColorCell ()
@property (weak, nonatomic) IBOutlet UILabel *red;
@property (weak, nonatomic) IBOutlet UILabel *green;
@property (weak, nonatomic) IBOutlet UILabel *blue;
@property (weak, nonatomic) IBOutlet UILabel *hex;
@property (weak, nonatomic) IBOutlet UIView *colorView;

@end


@implementation ColorSingleColorCell

- (void)setColorInformationWith:(NSString*)hexColor
{
    //转换hex值
    unsigned int red ,green,blue;
    
    NSScanner *scanner = [NSScanner scannerWithString:[hexColor substringWithRange:NSMakeRange(1, 2)]];
    [scanner scanHexInt:&red];
    
    scanner = [NSScanner scannerWithString:[hexColor substringWithRange:NSMakeRange(3, 2)]];
    [scanner scanHexInt:&green];
    
    scanner = [NSScanner scannerWithString:[hexColor substringWithRange:NSMakeRange(5, 2)]];
    [scanner scanHexInt:&blue];
    
    
    self.red.text = [NSString stringWithFormat:@"%d",red];
    self.green.text = [NSString stringWithFormat:@"%d",green];
    self.blue.text = [NSString stringWithFormat:@"%d",blue];
    self.hex.text = hexColor;
    
    self.colorView.backgroundColor = [UIColor colorWithRed:red/255.0 green:green/255.0 blue:blue/255.0 alpha:1];
}

- (void)awakeFromNib {
    // Initialization code
}

- (void)setSelected:(BOOL)selected animated:(BOOL)animated {
    [super setSelected:selected animated:animated];

    // Configure the view for the selected state
}

@end
