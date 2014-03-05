//
//  ColorCell.m
//  ColorPicker
//
//  Created by Mango on 14-3-4.
//  Copyright (c) 2014年 Mango. All rights reserved.
//

#import "ColorCell.h"

@interface ColorCell ()

@end

@implementation ColorCell

- (id)initWithStyle:(UITableViewCellStyle)style reuseIdentifier:(NSString *)reuseIdentifier
{
    self = [super initWithStyle:style reuseIdentifier:reuseIdentifier];
    if (self) {
        UIImageView * backgroudImage = [[UIImageView alloc]initWithImage:[UIImage imageNamed:@"列表.png"]];
        [self setBackgroundView:backgroudImage];
    }
    return self;
}

- (void)setSelected:(BOOL)selected animated:(BOOL)animated
{
    [super setSelected:selected animated:animated];

    // Configure the view for the selected state
}

@end
