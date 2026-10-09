#import "TCOriginalDesign.h"
#import "TCColorUtilities.h"

@implementation TCOriginalImageButton
- (void)layoutSubviews {
    [super layoutSubviews];
    CGSize size=self.currentImage.size;
    CGFloat scale=self.artworkScale > 0 ? self.artworkScale : MIN(self.bounds.size.width/MAX(1,size.width),self.bounds.size.height/MAX(1,size.height));
    size=CGSizeMake(size.width*scale,size.height*scale);
    self.imageView.frame=CGRectMake((self.bounds.size.width-size.width)/2,(self.bounds.size.height-size.height)/2,size.width,size.height);
}
@end
@implementation TCOriginalNavigationController
- (UIViewController *)childViewControllerForStatusBarStyle { return self.topViewController; }
- (UIViewController *)childViewControllerForStatusBarHidden { return self.topViewController; }
@end

@interface TCOriginalReadout ()
@property (nonatomic, strong) UIImageView *backdrop;
@property (nonatomic, strong) UIImageView *swatchBorder;
@property (nonatomic, strong, readwrite) UIView *swatch;
@property (nonatomic, strong) NSArray<UILabel *> *values;
@property (nonatomic, strong) UILabel *accessibleValues;
@end
@implementation TCOriginalReadout
- (instancetype)initWithFrame:(CGRect)frame {
    if ((self=[super initWithFrame:frame])) {
        self.backdrop=TCOriginalArtwork(@"196x793");
        self.swatch=[UIView new];
        self.swatchBorder=TCOriginalArtwork(@"42x793");
        [self addSubview:self.backdrop]; [self addSubview:self.swatch]; [self addSubview:self.swatchBorder];
        NSMutableArray *labels=[NSMutableArray new];
        for (NSUInteger i=0;i<4;i++) { UILabel *label=TCOriginalValueLabel(); [labels addObject:label]; [self addSubview:label]; }
        self.values=labels;
        self.accessibleValues=TCOriginalValueLabel();
        self.accessibleValues.numberOfLines=0;
        [self addSubview:self.accessibleValues];
        self.isAccessibilityElement=YES;
        self.accessibilityTraits=UIAccessibilityTraitStaticText;
    }
    return self;
}
- (void)setHex:(NSString *)hex {
    _hex=[TCNormalizeHexColor(hex) copy];
    self.swatch.backgroundColor=_hex ? TCUIColorFromHex(_hex) : UIColor.clearColor;
    unsigned int value=0;
    if (_hex) [[NSScanner scannerWithString:[_hex substringFromIndex:1]] scanHexInt:&value];
    self.values[0].text=_hex ? [NSString stringWithFormat:@"%u",(value>>16)&255] : @"—";
    self.values[1].text=_hex ? [NSString stringWithFormat:@"%u",(value>>8)&255] : @"—";
    self.values[2].text=_hex ? [NSString stringWithFormat:@"%u",value&255] : @"—";
    self.values[3].text=_hex ?: @"—";
    self.accessibilityLabel=_hex ? [NSString stringWithFormat:@"%@, %@",_hex,TCRGBDescription(_hex)] : NSLocalizedString(@"Tap a pixel or sample the center",nil);
    self.accessibleValues.text=_hex ? [NSString stringWithFormat:@"%@\nR %@\nG %@\nB %@",_hex,self.values[0].text,self.values[1].text,self.values[2].text] : @"—";
    [self setNeedsLayout];
}
- (void)setHistoryRow:(BOOL)historyRow { _historyRow=historyRow; self.backdrop.image=TCOriginalImage(historyRow ? @"列表" : @"196x793"); [self setNeedsLayout]; }
- (CGFloat)preferredHeightForWidth:(CGFloat)width {
    return [self preferredHeightForWidth:width traits:self.traitCollection];
}
- (CGFloat)preferredHeightForWidth:(CGFloat)width traits:(UITraitCollection *)traits {
    if (UIContentSizeCategoryIsAccessibilityCategory(traits.preferredContentSizeCategory)) {
        UIFont *font=[[UIFontMetrics metricsForTextStyle:UIFontTextStyleBody] scaledFontForFont:[UIFont systemFontOfSize:12] compatibleWithTraitCollection:traits];
        return MAX(100,font.lineHeight*4+24);
    }
    return (self.historyRow ? 85 : 95)*width/320.0;
}
- (void)layoutSubviews {
    [super layoutSubviews];
    CGFloat s=self.bounds.size.width/320.0;
    BOOL large=UIContentSizeCategoryIsAccessibilityCategory(self.traitCollection.preferredContentSizeCategory);
    self.backdrop.hidden=large; self.accessibleValues.hidden=!large;
    for (UILabel *label in self.values) label.hidden=large;
    if (large) {
        self.swatch.frame=CGRectMake(16,16,63,63); self.swatchBorder.frame=self.swatch.frame;
        self.accessibleValues.frame=CGRectMake(95,12,MAX(0,self.bounds.size.width-111),self.bounds.size.height-24);
        return;
    }
    CGFloat y=(self.bounds.size.height-63*s)/2;
    self.swatch.frame=CGRectMake(21*s,y,63*s,63*s); self.swatchBorder.frame=self.swatch.frame;
    self.backdrop.frame=self.historyRow ? self.bounds : CGRectMake(98*s,y,198*s,63*s);
    CGFloat x=(self.historyRow ? 132 : 140)*s;
    for (NSUInteger i=0;i<3;i++) self.values[i].frame=CGRectMake(x,y+(1+20*i)*s,36*s,20*s);
    self.values[3].frame=CGRectMake(218*s,y+23*s,80*s,20*s);
    for (UILabel *label in self.values) label.font=[[UIFontMetrics metricsForTextStyle:UIFontTextStyleBody] scaledFontForFont:[UIFont systemFontOfSize:12*s]];
}
- (void)traitCollectionDidChange:(UITraitCollection *)previous {
    [super traitCollectionDidChange:previous];
    if (![previous.preferredContentSizeCategory isEqual:self.traitCollection.preferredContentSizeCategory]) {
        self.accessibleValues.font=[[UIFontMetrics metricsForTextStyle:UIFontTextStyleBody] scaledFontForFont:[UIFont systemFontOfSize:12]];
        [self setNeedsLayout]; [self.superview setNeedsLayout];
    }
}
@end
