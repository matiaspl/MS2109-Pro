#import <AppKit/AppKit.h>
#import <AVFoundation/AVFoundation.h>
#import <CoreVideo/CoreVideo.h>
#include <stdint.h>
#include <stdlib.h>

#define W 1920
#define H 1080
#define TW 16
#define TH 8
#define COLS 120
#define FRAMES 2

#import "native_patch_view.h"

@interface Probe : NSObject <NSApplicationDelegate, AVCaptureVideoDataOutputSampleBufferDelegate> {
    uint8_t samples[FRAMES][3][COLS][3];
}
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) PatchView *view;
@property(nonatomic, strong) AVCaptureSession *session;
@property(nonatomic, strong) AVCaptureVideoDataOutput *output;
@property(nonatomic, strong) dispatch_queue_t queue;
@property(nonatomic, strong) NSString *outPath;
@property(nonatomic) int frameCount;
@property(nonatomic) CFAbsoluteTime ready;
@property(nonatomic) BOOL finished;
@property(nonatomic, strong) NSString *patternPath;
@property(nonatomic, strong) NSDictionary *colorMetadata;
- (void)finish:(NSString *)error;
@end

static uint8_t median(uint8_t *a, int n) {
    for (int i=1;i<n;i++) { uint8_t v=a[i]; int j=i-1; while(j>=0&&a[j]>v){a[j+1]=a[j];j--;} a[j+1]=v; }
    return (uint8_t)(((unsigned)a[(n-1)/2]+a[n/2]+1)/2);
}
static NSArray *jsonArray(uint8_t *v) {
    NSMutableArray *a=[NSMutableArray arrayWithCapacity:COLS];
    for(int i=0;i<COLS;i++) [a addObject:@(v[i])]; return a;
}

@implementation Probe
- (void)applicationDidFinishLaunching:(NSNotification *)note {
    NSScreen *target=nil;
    for(NSScreen *s in NSScreen.screens) {
        CGDirectDisplayID d=[s.deviceDescription[@"NSScreenNumber"] unsignedIntValue];
        if(d!=CGMainDisplayID()&&CGDisplayPixelsWide(d)==W&&CGDisplayPixelsHigh(d)==H&&[s.localizedName isEqual:@"HDMI TO USB"]) target=s;
    }
    if(!target || target.frame.size.width!=W || target.frame.size.height!=H || target.backingScaleFactor!=1) {
        fprintf(stderr,"HDMI TO USB 1920x1080 1:1 display unavailable\n"); [NSApp terminate:nil]; return;
    }
    NSString *pattern=self.patternPath;
    self.window=[[NSWindow alloc] initWithContentRect:NSMakeRect(0,0,W,H) styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:NO screen:target];
    self.window.opaque=YES; self.window.level=NSStatusWindowLevel+1; self.window.collectionBehavior=NSWindowCollectionBehaviorCanJoinAllSpaces;
    self.view=[[PatchView alloc] initWithFrame:NSMakeRect(0,0,W,H)]; self.view.pattern=loadNativePattern(pattern); self.view.patchSpace=target.colorSpace; self.window.colorSpace=target.colorSpace;
    if(!self.view.pattern){fprintf(stderr,"Invalid native pattern JSON\n");[NSApp terminate:nil];return;}
    self.window.contentView=self.view; [self.window orderFrontRegardless]; [self.window setFrame:target.frame display:YES]; [self.view display];
    [AVCaptureDevice requestAccessForMediaType:AVMediaTypeVideo completionHandler:^(BOOL granted) {
        dispatch_async(dispatch_get_main_queue(), ^{ if(granted) [self startCapture]; else { fprintf(stderr,"Camera permission denied for YUY2 Gradient Probe\n"); [NSApp terminate:nil]; } });
    }];
}
- (void)startCapture {
    AVCaptureDeviceDiscoverySession *ds=[AVCaptureDeviceDiscoverySession discoverySessionWithDeviceTypes:@[AVCaptureDeviceTypeExternal] mediaType:AVMediaTypeVideo position:AVCaptureDevicePositionUnspecified];
    AVCaptureDevice *device=nil;
    for(AVCaptureDevice *d in ds.devices) if([d.localizedName containsString:@"MS2109"]||[d.localizedName containsString:@"HDMI TO USB"]) { device=d; break; }
    if(!device){[self finish:@"MS2109 external camera not listed by AVFoundation"];return;}
    NSError *err=nil; AVCaptureDeviceInput *input=[AVCaptureDeviceInput deviceInputWithDevice:device error:&err];
    if(!input){[self finish:err.localizedDescription?:@"Could not create AVCaptureDeviceInput"];return;}
    self.session=[AVCaptureSession new];
    if([self.session canSetSessionPreset:AVCaptureSessionPreset1920x1080]) self.session.sessionPreset=AVCaptureSessionPreset1920x1080;
    if(![self.session canAddInput:input]){[self finish:@"Cannot add MS2109 camera input"];return;} [self.session addInput:input];
    self.output=[AVCaptureVideoDataOutput new]; self.output.alwaysDiscardsLateVideoFrames=YES;
    NSArray<NSNumber *> *types=self.output.availableVideoCVPixelFormatTypes; OSType chosen=0;
    for(NSNumber *n in types) if(n.unsignedIntValue==kCVPixelFormatType_422YpCbCr8_yuvs) chosen=kCVPixelFormatType_422YpCbCr8_yuvs;
    if(!chosen) for(NSNumber *n in types) if(n.unsignedIntValue==kCVPixelFormatType_422YpCbCr8) chosen=kCVPixelFormatType_422YpCbCr8;
    if(!chosen){[self finish:@"AVFoundation does not offer packed 4:2:2 output for this device"];return;}
    self.output.videoSettings=@{(id)kCVPixelBufferPixelFormatTypeKey:@(chosen)};
    if(![self.session canAddOutput:self.output]){[self finish:@"Cannot add 4:2:2 video output"];return;}
    [self.session addOutput:self.output]; self.queue=dispatch_queue_create("yuy2.gradient.probe",DISPATCH_QUEUE_SERIAL);
    [self.output setSampleBufferDelegate:self queue:self.queue];
    [self.session startRunning]; self.ready=CFAbsoluteTimeGetCurrent()+0.5;
    fprintf(stderr,"AVFoundation camera: %s; requested pixel format 0x%08x; collecting two frames in memory\n",device.localizedName.UTF8String,(unsigned)chosen);
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,120*NSEC_PER_SEC),dispatch_get_main_queue(),^{[self finish:@"Timed out waiting for two frames"];});
}
- (void)captureOutput:(AVCaptureOutput *)output didOutputSampleBuffer:(CMSampleBufferRef)buffer fromConnection:(AVCaptureConnection *)connection {
    if(self.finished||CFAbsoluteTimeGetCurrent()<self.ready||self.frameCount>=FRAMES)return;
    CVImageBufferRef image=CMSampleBufferGetImageBuffer(buffer); if(!image){dispatch_async(dispatch_get_main_queue(),^{[self finish:@"AVFoundation delivered no CVImageBuffer"];});return;}
    if (!self.colorMetadata) {
        CFDictionaryRef ca=CVBufferCopyAttachments(image,kCVAttachmentMode_ShouldPropagate);
        NSDictionary *attachments=CFBridgingRelease(ca);
        NSMutableDictionary *m=[NSMutableDictionary dictionary];
        for(id key in attachments) m[[key description]]=[attachments[key] description];
        CGColorSpaceRef color=(__bridge CGColorSpaceRef)attachments[(__bridge NSString*)kCVImageBufferCGColorSpaceKey];
        if(color) {
            CFStringRef name=CGColorSpaceCopyName(color);
            if(name) { m[@"color_space_name"]=[(__bridge NSString*)name copy]; CFRelease(name); }
            CFDataRef profile=CGColorSpaceCopyICCData(color);
            if(profile) { m[@"icc_profile_base64"]=[(__bridge NSData*)profile base64EncodedStringWithOptions:0]; CFRelease(profile); }
        }
        CFDictionaryRef sa=CMCopyDictionaryOfAttachments(kCFAllocatorDefault,buffer,kCMAttachmentMode_ShouldPropagate);
        NSDictionary *sampleAttachments=CFBridgingRelease(sa);
        NSMutableDictionary *sm=[NSMutableDictionary dictionary];
        for(id key in sampleAttachments) sm[[key description]]=[sampleAttachments[key] description];
        self.colorMetadata=@{@"pixel_buffer_attachments":m,@"sample_buffer_attachments":sm,@"format_description":[(__bridge id)CMFormatDescriptionGetExtensions(CMSampleBufferGetFormatDescription(buffer)) description]?:@"",@"pixel_format":@(CVPixelBufferGetPixelFormatType(image))};
    }
    CVPixelBufferLockBaseAddress(image,kCVPixelBufferLock_ReadOnly);
    size_t w=CVPixelBufferGetWidth(image),h=CVPixelBufferGetHeight(image),stride=CVPixelBufferGetBytesPerRow(image); OSType fmt=CVPixelBufferGetPixelFormatType(image); uint8_t *base=CVPixelBufferGetBaseAddress(image);
    if(w!=W||h!=H||!base||(fmt!=kCVPixelFormatType_422YpCbCr8_yuvs&&fmt!=kCVPixelFormatType_422YpCbCr8)){
        CVPixelBufferUnlockBaseAddress(image,kCVPixelBufferLock_ReadOnly); dispatch_async(dispatch_get_main_queue(),^{[self finish:[NSString stringWithFormat:@"Unexpected CVPixelBuffer %zux%zu 0x%08x",w,h,(unsigned)fmt]];});return;
    }
    int fi=self.frameCount++;
    for(int band=0;band<3;band++) for(int x=0;x<COLS;x++) {
        int stimulusBand=band, ty=band*(H/(3*TH))+(H/(3*TH))/2; uint8_t yy[32],cc[16],rr[16];int ny=0,nc=0;
        for(int y=ty*TH+2;y<ty*TH+6;y++){uint8_t *line=base+(size_t)y*stride;for(int xx=x*TW+4;xx<x*TW+12;xx++){size_t q=(size_t)(xx/2)*4;
            if(fmt==kCVPixelFormatType_422YpCbCr8_yuvs){yy[ny++]=line[q+((xx&1)?2:0)];if(!(xx&1)){cc[nc]=line[q+1];rr[nc++]=line[q+3];}}
            else {yy[ny++]=line[q+((xx&1)?3:1)];if(!(xx&1)){cc[nc]=line[q];rr[nc++]=line[q+2];}}
        }}
        samples[fi][stimulusBand][x][0]=median(yy,ny); samples[fi][stimulusBand][x][1]=median(cc,nc); samples[fi][stimulusBand][x][2]=median(rr,nc);
    }
    CVPixelBufferUnlockBaseAddress(image,kCVPixelBufferLock_ReadOnly);
    if(self.frameCount==FRAMES) dispatch_async(dispatch_get_main_queue(),^{[self finish:nil];});
}
- (void)finish:(NSString *)error {
    if(self.finished)return; self.finished=YES; if(self.session.isRunning)[self.session stopRunning]; [self.output setSampleBufferDelegate:nil queue:NULL];
    NSArray *names=@[@"Y",@"Cb",@"Cr"]; NSMutableArray *bands=[NSMutableArray array]; BOOL stable=YES;
    for(int k=0;k<3;k++) { NSMutableDictionary *b=[NSMutableDictionary dictionary]; b[@"name"]=names[k]; NSArray *keys=@[@"measured_Y",@"measured_Cb",@"measured_Cr"]; NSMutableArray *delta=[NSMutableArray array];
        for(int c=0;c<3;c++){uint8_t values[COLS];int maxD=0;for(int x=0;x<COLS;x++){values[x]=(uint8_t)(((unsigned)samples[0][k][x][c]+samples[1][k][x][c]+1)/2);int d=abs((int)samples[0][k][x][c]-(int)samples[1][k][x][c]);if(d>maxD)maxD=d;}b[keys[c]]=jsonArray(values);[delta addObject:@(maxD)];if(maxD>1)stable=NO;}
        b[@"repeat_frame_max_delta_Y_Cb_Cr"]=delta;[bands addObject:b];
    }
    NSDictionary *result=@{@"error":error?:[NSNull null],@"frames_captured":@(self.frameCount),@"raw_frames_saved":@NO,@"renderer":@"direct display-native RGB patches",@"source_color_space":self.view.patchSpace.localizedName,@"capture_path":@"AVFoundation native 4:2:2",@"procamp_controlled":@NO,@"color_metadata":self.colorMetadata?:@{},@"repeat_stable_within_1_code":@(stable),@"format":@"YUY2-compatible packed 4:2:2 1920x1080",@"tile_pixels":@[@16,@8],@"bands":bands};
    NSData *json=[NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:nil];if(json){[json writeToFile:self.outPath options:NSDataWritingAtomic error:nil];fwrite(json.bytes,1,json.length,stdout);fputc('\n',stdout);fflush(stdout);}
    [self.window close];[NSApp terminate:nil];
}
@end

int main(int argc,const char **argv) {@autoreleasepool { if(argc!=3){fprintf(stderr,"usage: transfer_native_metadata PATTERN_JSON OUTPUT_JSON\n");return 2;} [NSApplication sharedApplication];[NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];Probe *p=[Probe new];p.patternPath=@(argv[1]);p.outPath=@(argv[2]);[NSApp setDelegate:p];[NSApp run];return 0;}}
