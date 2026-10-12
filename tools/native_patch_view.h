#import <Cocoa/Cocoa.h>
// Direct RGB code patches in the active display color space. No raster input.
@interface PatchView : NSView
@property(nonatomic,strong) NSDictionary *pattern;
@property(nonatomic,strong) NSColorSpace *patchSpace;
@end
@implementation PatchView
-(BOOL)isFlipped{return YES;}
-(void)drawRect:(NSRect)dirty {
    CGContextRef ctx=NSGraphicsContext.currentContext.CGContext;
    CGContextSetShouldAntialias(ctx,false);
    NSArray *names=@[@"Y",@"Cb",@"Cr"];
    for(int band=0;band<3;band++){
        NSArray *values=self.pattern[@"bands"][names[band]][@"rgb"];
        for(int x=0;x<COLS;x++){
            NSArray *rgb=values[x];CGFloat c[4]={[rgb[0] doubleValue]/255.,[rgb[1] doubleValue]/255.,[rgb[2] doubleValue]/255.,1};
            [[NSColor colorWithColorSpace:self.patchSpace components:c count:4] setFill];
            for(int y=band*(H/TH/3);y<(band+1)*(H/TH/3);y++)NSRectFill(NSMakeRect(x*TW,y*TH,TW,TH));
        }
    }
}
@end
static NSDictionary *loadNativePattern(NSString *path){
 NSData *data=[NSData dataWithContentsOfFile:path];if(!data)return nil;
 NSDictionary *p=[NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
 if(![p isKindOfClass:NSDictionary.class])return nil;
 if(![p[@"tile_pixels"] isEqual:@[@TW,@TH]])return nil;
 for(NSString *name in @[@"Y",@"Cb",@"Cr"]){
  NSArray *v=p[@"bands"][name][@"rgb"];if(![v isKindOfClass:NSArray.class]||v.count!=COLS)return nil;
  for(NSArray *rgb in v){if(![rgb isKindOfClass:NSArray.class]||rgb.count!=3)return nil;for(id n in rgb)if(![n isKindOfClass:NSNumber.class]||[n doubleValue]!=[n intValue]||[n intValue]<0||[n intValue]>255)return nil;}
 }
 return p;
}
