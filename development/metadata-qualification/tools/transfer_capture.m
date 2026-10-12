#import <Cocoa/Cocoa.h>
#import <libuvc/libuvc.h>
#import <CommonCrypto/CommonDigest.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define W 1920
#define H 1080
#define TW 16
#define TH 8
#define COLS 120
#define FRAMES 2
#define FRAME_BYTES (W*H*2)

#import "native_patch_view.h"

@interface Capture : NSObject { @public uvc_stream_ctrl_t ctrl; uint8_t samples[FRAMES][3][COLS][3]; }
@property NSWindow *window; @property PatchView *view; @property uvc_device_handle_t *handle;
@property BOOL streaming,finished,controlsSaved;
@property int16_t oldB,oldH; @property uint16_t oldC,oldS;
@property int16_t setB,setH; @property uint16_t setC,setS;
@property NSDictionary *restoreTarget;
@property int frameCount;
@property CFAbsoluteTime ready; @property NSString *outPath;
-(void)finish:(NSString*)error;
@end

static BOOL controls(uvc_device_handle_t*h,int16_t*b,uint16_t*c,int16_t*hu,uint16_t*s,enum uvc_req_code q){return uvc_get_brightness(h,b,q)>=0&&uvc_get_contrast(h,c,q)>=0&&uvc_get_hue(h,hu,q)>=0&&uvc_get_saturation(h,s,q)>=0;}
static BOOL setControls(uvc_device_handle_t*h,int16_t b,uint16_t c,int16_t hu,uint16_t s){return uvc_set_brightness(h,b)>=0&&uvc_set_contrast(h,c)>=0&&uvc_set_hue(h,hu)>=0&&uvc_set_saturation(h,s)>=0;}
static uint8_t med(uint8_t*a,int n){for(int i=1;i<n;i++){uint8_t v=a[i];int j=i-1;while(j>=0&&a[j]>v){a[j+1]=a[j];j--;}a[j+1]=v;}return (uint8_t)(((unsigned)a[(n-1)/2]+a[n/2]+1)/2);}
static void cb(uvc_frame_t*f,void*u){Capture*p=(__bridge Capture*)u;if(p.finished||CFAbsoluteTimeGetCurrent()<p.ready||p.frameCount>=FRAMES)return;
 if(f->width!=W||f->height!=H||f->frame_format!=UVC_FRAME_FORMAT_YUYV||f->data_bytes!=FRAME_BYTES){dispatch_async(dispatch_get_main_queue(),^{[p finish:@"Unexpected YUY2 frame format/dimensions"];});return;}
 const uint8_t*src=f->data;int fi=p.frameCount++;
 for(int band=0;band<3;band++)for(int x=0;x<COLS;x++){int stimulusBand=band;uint8_t yy[32],cc[16],rr[16];int ny=0,nc=0;int ty=band*(H/(3*TH))+(H/(3*TH))/2;
  for(int y=ty*TH+2;y<ty*TH+6;y++){const uint8_t*line=src+(size_t)y*W*2;for(int xx=x*TW+4;xx<x*TW+12;xx++){int q=(xx/2)*4;yy[ny++]=line[q+((xx&1)?2:0)];if(!(xx&1)){cc[nc]=line[q+1];rr[nc++]=line[q+3];}}}
  p->samples[fi][stimulusBand][x][0]=med(yy,ny);p->samples[fi][stimulusBand][x][1]=med(cc,nc);p->samples[fi][stimulusBand][x][2]=med(rr,nc);
 }
 if(p.frameCount==FRAMES)dispatch_async(dispatch_get_main_queue(),^{[p finish:nil];});
}
static NSArray*arr(uint8_t values[COLS]){NSMutableArray*a=[NSMutableArray arrayWithCapacity:COLS];for(int i=0;i<COLS;i++)[a addObject:@(values[i])];return a;}
static NSArray*chan(Capture*p,int band,int c){uint8_t v[COLS];for(int x=0;x<COLS;x++)v[x]=(uint8_t)(((unsigned)p->samples[0][band][x][c]+p->samples[1][band][x][c]+1)/2);return arr(v);}
static int maxDelta(Capture*p,int band,int c){int m=0;for(int x=0;x<COLS;x++){int d=abs((int)p->samples[0][band][x][c]-(int)p->samples[1][band][x][c]);if(d>m)m=d;}return m;}
@implementation Capture
-(void)finish:(NSString*)error{if(self.finished)return;self.finished=YES;BOOL restored=NO;int16_t b=0,h=0;uint16_t c=0,s=0;
 if(self.handle&&self.controlsSaved){restored=setControls(self.handle,self.oldB,self.oldC,self.oldH,self.oldS)&&controls(self.handle,&b,&c,&h,&s,UVC_GET_CUR)&&b==self.oldB&&c==self.oldC&&h==self.oldH&&s==self.oldS;}
 NSMutableDictionary*m=[@{@"error":error?:[NSNull null],@"frames_captured":@(self.frameCount),@"procamp_requested":@{@"brightness":@(self.setB),@"contrast":@(self.setC),@"hue":@(self.setH),@"saturation":@(self.setS)},@"procamp_restore_target":self.restoreTarget?:[NSNull null],@"procamp_restored":@(restored),@"procamp_after_restore":@{@"brightness":@(b),@"contrast":@(c),@"hue":@(h),@"saturation":@(s)},@"raw_frames_saved":@NO} mutableCopy];
 NSArray*names=@[@"Y",@"Cb",@"Cr"];NSMutableArray*bands=[NSMutableArray array];BOOL stable=YES;
 for(int k=0;k<3;k++){NSMutableDictionary*q=[NSMutableDictionary dictionary];q[@"name"]=names[k];q[@"measured_Y"]=chan(self,k,0);q[@"measured_Cb"]=chan(self,k,1);q[@"measured_Cr"]=chan(self,k,2);NSMutableArray*d=[NSMutableArray array];for(int c0=0;c0<3;c0++){int x=maxDelta(self,k,c0);[d addObject:@(x)];if(x>1)stable=NO;}q[@"repeat_frame_max_delta_Y_Cb_Cr"]=d;[bands addObject:q];}
 m[@"renderer"]=@"direct display-native RGB patches";m[@"source_color_space"]=self.view.patchSpace.localizedName;m[@"bands"]=bands;m[@"repeat_stable_within_1_code"]=@(stable);m[@"device_id"]=@"0x534d:0x2109";m[@"format"]=@"YUY2 1920x1080";m[@"tile_pixels"]=@[@16,@8];
 NSError*e=nil;NSData*j=[NSJSONSerialization dataWithJSONObject:m options:NSJSONWritingPrettyPrinted error:&e];if(j){[j writeToFile:self.outPath options:NSDataWritingAtomic error:nil];fwrite(j.bytes,1,j.length,stdout);fputc('\n',stdout);fflush(stdout);}else fprintf(stderr,"JSON serialization: %s\n",e.description.UTF8String);
 if(self.streaming){uvc_stop_streaming(self.handle);self.streaming=NO;}if(self.handle){uvc_close(self.handle);self.handle=NULL;}[self.window close];[NSApp terminate:nil];
}
@end

int main(int argc,const char**argv){@autoreleasepool{if(argc!=6){fprintf(stderr,"usage: capture PATTERN_JSON OUTPUT_JSON B C S\n");return 2;}
 [NSApplication sharedApplication];[NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];NSScreen*screen=nil;for(NSScreen*s in NSScreen.screens){CGDirectDisplayID d=[s.deviceDescription[@"NSScreenNumber"] unsignedIntValue];if(d!=CGMainDisplayID()&&CGDisplayPixelsWide(d)==W&&CGDisplayPixelsHigh(d)==H&&[s.localizedName isEqual:@"HDMI TO USB"])screen=s;}
 if(!screen||screen.frame.size.width!=W||screen.frame.size.height!=H||screen.backingScaleFactor!=1){fprintf(stderr,"HDMI TO USB 1920x1080 1:1 display unavailable\n");return 2;}
 Capture*p=[Capture new];p.outPath=@(argv[2]);p.setB=(int16_t)atoi(argv[3]);p.setC=(uint16_t)atoi(argv[4]);p.setH=0;p.setS=(uint16_t)atoi(argv[5]);p.window=[[NSWindow alloc]initWithContentRect:NSMakeRect(0,0,W,H) styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:NO screen:screen];p.window.opaque=YES;p.window.level=NSStatusWindowLevel+1;p.window.collectionBehavior=NSWindowCollectionBehaviorCanJoinAllSpaces;p.view=[[PatchView alloc]initWithFrame:NSMakeRect(0,0,W,H)];p.view.pattern=loadNativePattern(@(argv[1]));p.view.patchSpace=screen.colorSpace;p.window.colorSpace=screen.colorSpace;if(!p.view.pattern){fprintf(stderr,"Invalid native pattern JSON\n");return 2;}p.window.contentView=p.view;[p.window orderFrontRegardless];[p.window setFrame:screen.frame display:YES];[p.view display];
 uvc_context_t*ctx=NULL;uvc_error_t e=uvc_init(&ctx,NULL);if(e<0){uvc_perror(e,"uvc_init");return 2;}uvc_device_t*dev=NULL;e=uvc_find_device(ctx,&dev,0x534d,0x2109,NULL);if(e<0){uvc_perror(e,"uvc_find_device");return 2;}uvc_device_handle_t*h=NULL;e=uvc_open(dev,&h);if(e<0){uvc_perror(e,"uvc_open");return 2;}p.handle=h;int16_t oldB=0,oldH=0;uint16_t oldC=0,oldS=0;if(!controls(h,&oldB,&oldC,&oldH,&oldS,UVC_GET_CUR)){[p finish:@"Could not read original procamp controls"];return 2;}p.oldB=oldB;p.oldC=oldC;p.oldH=oldH;p.oldS=oldS;p.controlsSaved=YES;p.restoreTarget=@{@"brightness":@(p.oldB),@"contrast":@(p.oldC),@"hue":@(p.oldH),@"saturation":@(p.oldS)};
 if(!setControls(h,p.setB,p.setC,p.setH,p.setS)){[p finish:@"Could not apply requested procamp controls"];return 2;}int16_t b=0,hu=0;uint16_t c=0,s=0;if(!controls(h,&b,&c,&hu,&s,UVC_GET_CUR)||b!=p.setB||c!=p.setC||hu!=p.setH||s!=p.setS){[p finish:@"Procamp GET_CUR did not match request"];return 2;}
 e=uvc_get_stream_ctrl_format_size(h,&p->ctrl,UVC_FRAME_FORMAT_YUYV,W,H,5);if(e<0){[p finish:@"Could not select YUY2 1080p mode"];return 2;}e=uvc_start_streaming(h,&p->ctrl,cb,(__bridge void*)p,0);if(e<0){[p finish:@"Could not start YUY2 capture"];return 2;}p.streaming=YES;p.ready=CFAbsoluteTimeGetCurrent()+3;fprintf(stderr,"Showing Y/Cb/Cr gradients; requested B/C/H/S=%d/%u/%d/%u\n",p.setB,p.setC,p.setH,p.setS);fflush(stderr);dispatch_after(dispatch_time(DISPATCH_TIME_NOW,120*NSEC_PER_SEC),dispatch_get_main_queue(),^{[p finish:@"Timed out"];});[NSApp run];uvc_exit(ctx);return 0;}}
