// Color patch display and AVFoundation YUV acquisition. No device/register writes.
#import <Cocoa/Cocoa.h>
#import <AVFoundation/AVFoundation.h>
#import <CoreGraphics/CoreGraphics.h>
#import <CoreVideo/CoreVideo.h>
#import <ImageIO/ImageIO.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>
#import <ScreenCaptureKit/ScreenCaptureKit.h>
#import <objc/runtime.h>
#import <objc/message.h>
#import <dlfcn.h>

static NSString *fourcc(OSType v) {
    for(int i=0;i<4;i++){unsigned c=(v>>(i*8))&255;if(c<32 || c>126)return [NSString stringWithFormat:@"0x%08x",(unsigned)v];}
    char b[5]={(v>>24)&255,(v>>16)&255,(v>>8)&255,v&255,0};
    return [NSString stringWithUTF8String:b] ?: [NSString stringWithFormat:@"0x%08x",(unsigned)v];
}
static void jsonWrite(id obj, NSString *path) {
    NSError *e=nil; NSData *d=[NSJSONSerialization dataWithJSONObject:obj options:NSJSONWritingPrettyPrinted error:&e];
    if (!d || ![d writeToFile:path options:NSDataWritingAtomic error:&e]) {
        fprintf(stderr,"JSON error: %s\n",e.description.UTF8String); exit(2);
    }
}
// Read-only private API, guarded by the runtime schema. Never calls a setter.
static NSDictionary *colorState(void) {
    NSMutableDictionary *out=[NSMutableDictionary dictionary];
    out[@"api"]=@"CoreBrightness private API; interpretation guarded by runtime type encoding";
    void *handle=dlopen("/System/Library/PrivateFrameworks/CoreBrightness.framework/CoreBrightness",RTLD_LAZY);
    if(!handle) {out[@"available"]=@NO;return out;}
    Class cls=NSClassFromString(@"CBBlueLightClient");id client=[cls new];
    SEL sel=NSSelectorFromString(@"getBlueLightStatus:");Method method=class_getInstanceMethod(cls,sel);
    if(method) {
        const char *encoding=method_getTypeEncoding(method);out[@"status_type_encoding"]=@(encoding);
        // BOOL auto-enabled/enabled/sun-permitted, int mode, two (hour,minute) pairs,
        // uint64 disable flags, BOOL availability. Reject any changed layout.
        if(strcmp(encoding,"B24@0:8^{?=BBBi{?={?=ii}{?=ii}}QB}16")==0) {
            uint8_t status[512]={0};BOOL ok=((BOOL(*)(id,SEL,void*))objc_msgSend)(client,sel,status);
            NSMutableString *hex=[NSMutableString string];for(int i=0;i<40;i++)[hex appendFormat:@"%02x",status[i]];
            out[@"night_shift_status_read_ok"]=@(ok);out[@"night_shift_status_hex"]=hex;
            if(ok) {
                out[@"night_shift_api_auto_enabled"]=@(status[0]!=0);
                out[@"night_shift_api_reported_enabled"]=@(status[1]!=0);
                out[@"night_shift_api_sun_schedule_allowed"]=@(status[2]!=0);
                out[@"night_shift_effect_state_verified"]=@NO;
                out[@"status_field_validation"]=@"Dictionary field mapping only: AutoBlueReductionEnabled byte 0; BlueReductionEnabled byte 1. Does not establish visual effect activity.";
                out[@"night_shift_api_limitation"]=@"This flag reported zero during the user-confirmed enabled baseline. Do not use it to infer whether Night Shift affects the output.";
            }
        }
    }
    for(NSString *name in @[@"getStrength:",@"getCCT:"]) {
        sel=NSSelectorFromString(name);method=class_getInstanceMethod(cls,sel);
        if(method && strcmp(method_getTypeEncoding(method),"B24@0:8^f16")==0) {
            float v=0;BOOL ok=((BOOL(*)(id,SEL,float*))objc_msgSend)(client,sel,&v);
            if(ok) out[[name isEqual:@"getStrength:"] ? @"night_shift_strength" : @"night_shift_configured_cct_kelvin"]=@(v);
        }
    }
    cls=NSClassFromString(@"CBAdaptationClient");client=[cls new];sel=NSSelectorFromString(@"getEnabled");method=class_getInstanceMethod(cls,sel);
    if(method && strcmp(method_getTypeEncoding(method),"B16@0:8")==0) out[@"true_tone_enabled"]=@(((BOOL(*)(id,SEL))objc_msgSend)(client,sel));
    return out;
}
static NSArray *screensInfo(void) {
    NSMutableArray *out=[NSMutableArray array];
    for(NSScreen *s in NSScreen.screens) {
        CGDirectDisplayID did=[s.deviceDescription[@"NSScreenNumber"] unsignedIntValue];
        NSData *icc=s.colorSpace.ICCProfileData;
        [out addObject:@{@"name":s.localizedName,@"display_id":@(did),@"main":@(did==CGMainDisplayID()),
            @"width":@(CGDisplayPixelsWide(did)),@"height":@(CGDisplayPixelsHigh(did)),
            @"frame":NSStringFromRect(s.frame),@"scale":@(s.backingScaleFactor),
            @"profile":s.colorSpace.localizedName ?: @"unknown",@"profile_bytes":@(icc.length)}];
    } return out;
}
static NSScreen *targetChartScreen(size_t width,size_t height) {
    NSScreen *target=nil;
    for(NSScreen *screen in NSScreen.screens) {
        CGDirectDisplayID did=[screen.deviceDescription[@"NSScreenNumber"] unsignedIntValue];
        if(did!=CGMainDisplayID() && CGDisplayPixelsWide(did)==width && CGDisplayPixelsHigh(did)==height && [screen.localizedName isEqual:@"HDMI TO USB"]) {
            if(target)return nil;
            target=screen;
        }
    }
    if(!target || target.frame.size.width!=width || target.frame.size.height!=height || target.backingScaleFactor!=1.0)return nil;
    return target;
}
static NSArray *devicesInfo(void) {
    NSMutableArray *out=[NSMutableArray array];
    for(AVCaptureDevice *d in [AVCaptureDevice devicesWithMediaType:AVMediaTypeVideo]) {
        NSMutableArray *formats=[NSMutableArray array];
        for(AVCaptureDeviceFormat *f in d.formats) {
            CMVideoDimensions dim=CMVideoFormatDescriptionGetDimensions(f.formatDescription);
            NSMutableArray *rates=[NSMutableArray array];
            for(AVFrameRateRange *r in f.videoSupportedFrameRateRanges)
                [rates addObject:@{@"min":@(r.minFrameRate),@"max":@(r.maxFrameRate)}];
            [formats addObject:@{@"width":@(dim.width),@"height":@(dim.height),
                @"subtype":fourcc(CMFormatDescriptionGetMediaSubType(f.formatDescription)),@"rates":rates}];
        }
        [out addObject:@{@"name":d.localizedName,@"id":d.uniqueID,@"formats":formats}];
    } return out;
}
@interface PatchView : NSView
@property NSDictionary *pattern;
@property NSColorSpace *patchSpace;
@property NSImage *fullFrameImage;
@end
@implementation PatchView
-(BOOL)isFlipped {return YES;}
-(void)drawRect:(NSRect)dirty {
    if(self.fullFrameImage) {
        [self.fullFrameImage drawInRect:self.bounds fromRect:NSZeroRect
            operation:NSCompositingOperationCopy fraction:1.0 respectFlipped:YES
            hints:@{NSImageHintInterpolation:@(NSImageInterpolationNone)}];
        return;
    }
    [[NSColor colorWithColorSpace:self.patchSpace components:(CGFloat[]){0,0,0,1} count:4] setFill]; NSRectFill(self.bounds);
    for(NSDictionary *p in self.pattern[@"patches"]) {
        NSArray *rgb=p[@"rgb"]; CGFloat c[4]={[rgb[0] doubleValue]/255.,[rgb[1] doubleValue]/255.,[rgb[2] doubleValue]/255.,1};
        [[NSColor colorWithColorSpace:self.patchSpace components:c count:4] setFill];
        NSArray *r=p[@"rect"]; NSRectFill(NSMakeRect([r[0] doubleValue],[r[1] doubleValue],[r[2] doubleValue],[r[3] doubleValue]));
    }
}
@end
static void refreshChart(NSWindow *window,NSScreen *screen,NSDictionary *pattern,NSImage *fullFrameImage,NSString *space,NSString *out,NSMutableDictionary *metadata) {
    // On the target display the chart must cover the macOS menu bar so every
    // patch keeps its declared geometry. The screen-change observer orders it
    // out immediately if that display disappears.
    window.level=NSStatusWindowLevel+1;window.colorSpace=screen.colorSpace;
    // The pattern must be the HDMI source even when this helper was launched
    // from an accessory/background process. Raise and activate it explicitly;
    // the stream-level patch fit remains the final check of visible output.
    [NSApp activateIgnoringOtherApps:YES];
    PatchView *view=(PatchView*)window.contentView;view.pattern=pattern;view.fullFrameImage=fullFrameImage;
    view.patchSpace=[space isEqual:@"native"] ? screen.colorSpace : NSColorSpace.sRGBColorSpace;
    NSMutableArray *reference=[NSMutableArray array];
    for(NSDictionary *p in (pattern[@"patches"] ?: @[])) {
        NSArray *rgb=p[@"rgb"]; CGFloat c[4]={[rgb[0] doubleValue]/255.,[rgb[1] doubleValue]/255.,[rgb[2] doubleValue]/255.,1};
        NSColor *color=[[NSColor colorWithColorSpace:view.patchSpace components:c count:4] colorUsingColorSpace:screen.colorSpace];
        NSMutableDictionary *r=[p mutableCopy];r[@"expected_display_rgb"] = @[@(color.redComponent*255),@(color.greenComponent*255),@(color.blueComponent*255)];
        [reference addObject:r];
    }
    metadata[@"patch_reference"]=reference;
    metadata[@"chart_kind"]=fullFrameImage ? @"full-frame-raster" : @"color-patches";
    // The source PNG dimensions were checked from its CGImage before this
    // NSImage was created. AppKit may add a 2x backing representation while
    // drawing, so its mutable representation list is not the source raster size.
    metadata[@"full_frame_image_size"]=fullFrameImage ? @[@((NSInteger)fullFrameImage.size.width),@((NSInteger)fullFrameImage.size.height)] : NSNull.null;
    [window setFrame:screen.frame display:YES];[view setNeedsDisplay:YES];[view display];
    [window makeKeyAndOrderFront:nil];[window orderFrontRegardless];
    metadata[@"window_frame"]=NSStringFromRect(window.frame);metadata[@"window_screen"]=window.screen.localizedName ?: @"none";
    NSBitmapImageRep *render=[view bitmapImageRepForCachingDisplayInRect:view.bounds];
    [view cacheDisplayInRect:view.bounds toBitmapImageRep:render];
    [[render representationUsingType:NSBitmapImageFileTypePNG properties:@{}] writeToFile:[out stringByAppendingPathComponent:@"source-render.png"] atomically:YES];
    metadata[@"render_image_space"]=render.colorSpace.localizedName ?: @"unknown";
    metadata[@"source_screenshot_available"]=@NO;
    [screen.colorSpace.ICCProfileData writeToFile:[out stringByAppendingPathComponent:@"display-profile.icc"] atomically:YES];
}
static NSWindow *presentChart(NSScreen *screen,NSDictionary *pattern,NSImage *fullFrameImage,NSString *space,NSString *out,NSMutableDictionary *metadata) {
    NSWindow *window=[[NSWindow alloc] initWithContentRect:screen.frame styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:NO screen:screen];
    window.releasedWhenClosed=NO;window.level=NSStatusWindowLevel+1;window.opaque=YES;
    window.collectionBehavior=NSWindowCollectionBehaviorCanJoinAllSpaces|NSWindowCollectionBehaviorFullScreenAuxiliary|NSWindowCollectionBehaviorStationary;
    PatchView *view=[[PatchView alloc] initWithFrame:NSMakeRect(0,0,screen.frame.size.width,screen.frame.size.height)];
    window.contentView=view;
    refreshChart(window,screen,pattern,fullFrameImage,space,out,metadata);
    return window;
}
@interface Probe : NSObject <AVCaptureVideoDataOutputSampleBufferDelegate>
@property AVCaptureSession *session;
@property NSWindow *window;
@property NSString *out;
@property NSMutableDictionary *metadata;
@property NSInteger count, wanted;
@property CFAbsoluteTime ready;
@property BOOL finished;
@end
@implementation Probe
-(void)captureOutput:(AVCaptureOutput *)output didOutputSampleBuffer:(CMSampleBufferRef)sample fromConnection:(AVCaptureConnection *)connection {
    if(self.finished || CFAbsoluteTimeGetCurrent()<self.ready) return;
    CVPixelBufferRef b=CMSampleBufferGetImageBuffer(sample); if(!b) return;
    CVPixelBufferLockBaseAddress(b,kCVPixelBufferLock_ReadOnly);
    size_t w=CVPixelBufferGetWidth(b),h=CVPixelBufferGetHeight(b),stride=CVPixelBufferGetBytesPerRow(b);
    OSType type=CVPixelBufferGetPixelFormatType(b);
    // Packed YUV records samples; optional BGRA records the host RGB conversion.
    if(type!=kCVPixelFormatType_422YpCbCr8 && type!=kCVPixelFormatType_422YpCbCr8_yuvs && type!=kCVPixelFormatType_32BGRA) {
        fprintf(stderr,"Unexpected delivered pixel format %s\n",fourcc(type).UTF8String); self.finished=YES;
        CVPixelBufferUnlockBaseAddress(b,kCVPixelBufferLock_ReadOnly); dispatch_async(dispatch_get_main_queue(),^{[NSApp terminate:nil];}); return;
    }
    size_t bytesPerPixel=type==kCVPixelFormatType_32BGRA?4:2;
    NSMutableData *data=[NSMutableData dataWithLength:w*h*bytesPerPixel];
    for(size_t y=0;y<h;y++) memcpy((uint8_t*)data.mutableBytes+y*w*bytesPerPixel,(uint8_t*)CVPixelBufferGetBaseAddress(b)+y*stride,w*bytesPerPixel);
    NSDictionary *atts=CFBridgingRelease(CVBufferCopyAttachments(b,kCVAttachmentMode_ShouldPropagate));
    NSMutableDictionary *safe=[NSMutableDictionary dictionary];
    for(id k in atts) safe[[k description]]=[atts[k] description];
    NSString *name=[NSString stringWithFormat:@"frame-%03ld.%@",(long)self.count,fourcc(type)];
    NSError *error=nil;
    if(![data writeToFile:[self.out stringByAppendingPathComponent:name] options:NSDataWritingAtomic error:&error]) {
        fprintf(stderr,"Frame write failed: %s\n",error.description.UTF8String); exit(3);
    }
    CMTime t=CMSampleBufferGetPresentationTimeStamp(sample);
    @synchronized(self.metadata) { [self.metadata[@"frames"] addObject:@{@"file":name,@"width":@(w),@"height":@(h),@"stride_saved":@(w*bytesPerPixel),
        @"pixel_format":fourcc(type),@"pts_seconds":@(CMTimeGetSeconds(t)),@"attachments":safe}]; }
    CVPixelBufferUnlockBaseAddress(b,kCVPixelBufferLock_ReadOnly);
    fprintf(stderr,"Captured %ld/%ld %zux%zu %s\n",(long)++self.count,(long)self.wanted,w,h,fourcc(type).UTF8String);
    if(self.count>=self.wanted) {
        self.finished=YES;
        @synchronized(self.metadata) { jsonWrite(self.metadata,[self.out stringByAppendingPathComponent:@"capture.json"]); }
        dispatch_async(dispatch_get_main_queue(),^{[self.session stopRunning]; [self.window close]; [NSApp terminate:nil];});
    }
}
@end
int main(int argc,const char *argv[]) {@autoreleasepool {
    [NSApplication sharedApplication]; [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
    NSMutableDictionary *args=[NSMutableDictionary dictionary];
    for(int i=1;i<argc;i++) {NSString *k=@(argv[i]); if([k hasPrefix:@"--"] && i+1<argc) args[k]=@(argv[++i]);}
    if(argc==1 || [@(argv[1]) isEqual:@"list"]) {
        NSDictionary *info=@{@"screens":screensInfo(),@"devices":devicesInfo(),@"macos_color_state":colorState(),
            @"camera_authorization":@([AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeVideo]),
            @"screen_capture_allowed":@(CGPreflightScreenCaptureAccess())};
        NSData *d=[NSJSONSerialization dataWithJSONObject:info options:NSJSONWritingPrettyPrinted error:nil];
        fwrite(d.bytes,1,d.length,stdout); puts(""); return 0;
    }
    NSString *out=args[@"--output"],*manifest=args[@"--manifest"],*transport=args[@"--transport"] ?: @"yuv";
    NSString *space=args[@"--render-space"] ?: @"native";
    if(!args[@"--frames"])args[@"--frames"]=@"8";
    if([args[@"--frames"] integerValue]<3 || [args[@"--frames"] integerValue]>100) {fprintf(stderr,"--frames must be 3..100\n");return 2;}
    if(!out || !manifest) {fprintf(stderr,"Usage: color_probe_macos --manifest pattern.json --output DIRECTORY [--transport yuv|avf420v|display] [--full-frame-image IMAGE.png] [--render-space native|srgb] [--frames N] [--seconds N] [--pixel-format yuv|bgra] [--observe-source DISPLAY_SOURCE_DIRECTORY]\n"); return 2;}
    if(![@[@"native",@"srgb"] containsObject:space] || ![@[@"yuv",@"avf420v",@"display"] containsObject:transport]) return 2;
    if(args[@"--pixel-format"] && ![@[@"yuv",@"bgra"] containsObject:args[@"--pixel-format"]])return 2;
    NSError *error=nil;
    if([[NSFileManager defaultManager] fileExistsAtPath:out]){fprintf(stderr,"Refusing to overwrite existing output directory\n");return 2;}
    [[NSFileManager defaultManager] createDirectoryAtPath:out withIntermediateDirectories:YES attributes:nil error:&error];
    NSDictionary *pattern=[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:manifest] options:0 error:&error];
    if(!pattern) {fprintf(stderr,"Pattern load failed: %s\n",error.description.UTF8String);return 2;}
    NSImage *fullFrameImage=nil;
    size_t rasterWidth=1920,rasterHeight=1080;
    if(args[@"--full-frame-image"]) {
        if(![transport isEqual:@"display"]) {fprintf(stderr,"--full-frame-image is supported only with --transport display\n");return 2;}
        NSString *imagePath=args[@"--full-frame-image"];
        if(!imagePath.isAbsolutePath) imagePath=[[[manifest stringByDeletingLastPathComponent] stringByAppendingPathComponent:imagePath] stringByStandardizingPath];
        CGImageSourceRef imageSource=CGImageSourceCreateWithURL((__bridge CFURLRef)[NSURL fileURLWithPath:imagePath],NULL);
        CGImageRef cgImage=imageSource ? CGImageSourceCreateImageAtIndex(imageSource,0,NULL) : NULL;
        if(imageSource) CFRelease(imageSource);
        if(!cgImage) {fprintf(stderr,"Full-frame chart image could not be decoded\n");return 2;}
        size_t imageWidth=CGImageGetWidth(cgImage),imageHeight=CGImageGetHeight(cgImage);
        if(imageWidth<640 || imageHeight<360 || imageWidth*9!=imageHeight*16) {fprintf(stderr,"Full-frame chart must be a 16:9 raster of at least 640x360 pixels\n");CFRelease(cgImage);return 2;}
        rasterWidth=imageWidth;rasterHeight=imageHeight;
        fullFrameImage=[[NSImage alloc] initWithCGImage:cgImage size:NSMakeSize(imageWidth,imageHeight)];CFRelease(cgImage);
    }
    NSScreen *screen=targetChartScreen(rasterWidth,rasterHeight);
    if(!screen) {
        NSArray<NSScreen *> *availableScreens=NSScreen.screens;
        fprintf(stderr,"Unique %zux%zu HDMI TO USB extended display not found at 1:1 scale; AppKit reports %lu screen(s):\n",
            rasterWidth,rasterHeight,(unsigned long)availableScreens.count);
        for(NSScreen *candidate in availableScreens) {
            CGDirectDisplayID did=[candidate.deviceDescription[@"NSScreenNumber"] unsignedIntValue];
            fprintf(stderr,"  %s pixels=%zux%zu frame=%.0fx%.0f scale=%.2f main=%s\n",
                candidate.localizedName.UTF8String,CGDisplayPixelsWide(did),CGDisplayPixelsHigh(did),
                candidate.frame.size.width,candidate.frame.size.height,candidate.backingScaleFactor,
                did==CGMainDisplayID()?"yes":"no");
        }
        return 2;
    }
    if([transport isEqual:@"display"]) {
        NSMutableDictionary *metadata=[@{@"screens":screensInfo(),@"render_space":space,@"patch_manifest":manifest,@"utc_started":[[NSDate date] description]} mutableCopy];
        NSWindow *window=presentChart(screen,pattern,fullFrameImage,space,out,metadata);
        __block NSData *activeProfile=screen.colorSpace.ICCProfileData;
        __block NSInteger displayGeneration=0,profileGeneration=0;
        NSString *readyPath=[out stringByAppendingPathComponent:@"display-ready.json"];
        metadata[@"target_display_available"]=@YES;metadata[@"display_profile_matches"]=@YES;
        metadata[@"display_generation"]=@(displayGeneration);metadata[@"display_profile_generation"]=@(profileGeneration);
        NSMutableArray *displayEvents=[NSMutableArray array];metadata[@"display_reconfiguration_events"]=displayEvents;
        jsonWrite(metadata,readyPath);
        [[NSNotificationCenter defaultCenter] addObserverForName:NSApplicationDidChangeScreenParametersNotification object:NSApp queue:[NSOperationQueue mainQueue] usingBlock:^(NSNotification *notification){
            NSScreen *target=targetChartScreen(rasterWidth,rasterHeight);NSMutableDictionary *event=[NSMutableDictionary dictionary];
            displayGeneration++;event[@"utc"]= [[NSDate date] description];event[@"target_display_available"]=@(target!=nil);
            metadata[@"display_generation"]=@(displayGeneration);
            metadata[@"screens"]=screensInfo();
            if(!target) {
                window.level=NSNormalWindowLevel;[window orderOut:nil];
                metadata[@"target_display_available"]=@NO;metadata[@"display_profile_matches"]=@NO;
                metadata[@"window_screen"]=@"none";event[@"display_profile_matches"]=@NO;
            } else {
                NSData *currentProfile=target.colorSpace.ICCProfileData;
                BOOL profileChanged=![currentProfile isEqualToData:activeProfile];
                if(profileChanged){activeProfile=currentProfile;profileGeneration++;metadata[@"display_profile_generation"]=@(profileGeneration);}
                event[@"display_id"]=target.deviceDescription[@"NSScreenNumber"] ?: @0;
                event[@"display_profile"]=target.colorSpace.localizedName ?: @"unknown";
                event[@"display_profile_changed"]=@(profileChanged);
                metadata[@"target_display_available"]=@YES;metadata[@"display_profile_matches"]=@YES;
                refreshChart(window,target,pattern,fullFrameImage,space,out,metadata);
            }
            [displayEvents addObject:event];jsonWrite(metadata,readyPath);
        }];
        double seconds=[args[@"--seconds"] doubleValue] ?: 30;
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)(seconds*NSEC_PER_SEC)),dispatch_get_main_queue(),^{[window close];[NSApp terminate:nil];});
        [NSApp run];return 0;
    }
    AVCaptureDevice *device=nil;
    for(AVCaptureDevice *d in [AVCaptureDevice devicesWithMediaType:AVMediaTypeVideo]) if([d.localizedName isEqual:@"MS2109-Pro"]) {
        if(device) {fprintf(stderr,"Ambiguous capture device\n");return 2;} device=d;
    }
    if(!device) {fprintf(stderr,"MS2109-Pro capture device not found\n");return 2;}
    AVCaptureDeviceFormat *chosen=nil; double fps=0;
    for(AVCaptureDeviceFormat *f in device.formats) {
        CMVideoDimensions dim=CMVideoFormatDescriptionGetDimensions(f.formatDescription);
        NSString *sub=fourcc(CMFormatDescriptionGetMediaSubType(f.formatDescription));
        NSString *wantedSub=[transport isEqual:@"yuv"] ? @"yuvs" : @"420v";
        if(dim.width!=1920 || dim.height!=1080 || ![sub isEqual:wantedSub]) continue;
        double maxFPS=0;for(AVFrameRateRange *r in f.videoSupportedFrameRateRanges) maxFPS=fmax(maxFPS,r.maxFrameRate);
        if([transport isEqual:@"avf420v"]){maxFPS=0;for(AVFrameRateRange *r in f.videoSupportedFrameRateRanges) if(r.maxFrameRate<=30.01)maxFPS=fmax(maxFPS,r.maxFrameRate);}
        if(!chosen || maxFPS>fps) {chosen=f;fps=maxFPS;}
    }
    if(!chosen) {fprintf(stderr,"Requested 1080p %s transport not available\n",transport.UTF8String); return 2;}
    Probe *probe=[Probe new]; probe.out=out;probe.wanted=[args[@"--frames"] integerValue] ?: 8;
    probe.metadata=[@{@"screens":screensInfo(),@"capture_device":device.localizedName,@"capture_device_id":device.uniqueID,
        @"transport_requested":transport,@"active_subtype":fourcc(CMFormatDescriptionGetMediaSubType(chosen.formatDescription)),
        @"utc_started":[[NSDate date] description],@"fps":@(fps),@"render_space":space,@"patch_manifest":manifest,@"frames":[NSMutableArray array]} mutableCopy];
    NSData *profile=screen.colorSpace.ICCProfileData;
    [profile writeToFile:[out stringByAppendingPathComponent:@"display-profile.icc"] atomically:YES];
    AVCaptureDeviceInput *input=[AVCaptureDeviceInput deviceInputWithDevice:device error:&error];
    if(!input) {fprintf(stderr,"AVFoundation input failed: %s\n",error.description.UTF8String);return 2;}
    probe.session=[AVCaptureSession new];
    if(![probe.session canAddInput:input]) return 2;[probe.session addInput:input];
    if(![device lockForConfiguration:&error]) {fprintf(stderr,"Format lock failed: %s\n",error.description.UTF8String);return 2;}
    device.activeFormat=chosen;
    for(AVFrameRateRange *r in chosen.videoSupportedFrameRateRanges) if(fabs(r.maxFrameRate-fps)<0.001)device.activeVideoMinFrameDuration=r.minFrameDuration;
    device.activeVideoMaxFrameDuration=device.activeVideoMinFrameDuration;
    AVCaptureVideoDataOutput *output=[AVCaptureVideoDataOutput new];output.alwaysDiscardsLateVideoFrames=YES;
    NSMutableArray *available=[NSMutableArray array];for(NSNumber *v in output.availableVideoCVPixelFormatTypes) [available addObject:fourcc(v.unsignedIntValue)];
    probe.metadata[@"available_output_pixel_formats"]=available;
    OSType delivered=[transport isEqual:@"yuv"] ? kCVPixelFormatType_422YpCbCr8_yuvs : kCVPixelFormatType_422YpCbCr8;
    if([args[@"--pixel-format"] isEqual:@"bgra"])delivered=kCVPixelFormatType_32BGRA;
    if(delivered==kCVPixelFormatType_32BGRA && ![output.availableVideoCVPixelFormatTypes containsObject:@(delivered)]) {fprintf(stderr,"BGRA output unavailable\n");return 2;}
    if(![output.availableVideoCVPixelFormatTypes containsObject:@(delivered)]) delivered=kCVPixelFormatType_422YpCbCr8_yuvs;
    if(![output.availableVideoCVPixelFormatTypes containsObject:@(delivered)]) {fprintf(stderr,"No packed 422 output available\n");return 2;}
    output.videoSettings=@{(id)kCVPixelBufferPixelFormatTypeKey:@(delivered)};
    [output setSampleBufferDelegate:probe queue:dispatch_queue_create("color-probe-capture",DISPATCH_QUEUE_SERIAL)];
    if(![probe.session canAddOutput:output]) return 2;[probe.session addOutput:output];
    if(args[@"--observe-source"]) {
        NSString *source=args[@"--observe-source"];
        NSDictionary *reference=[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:[source stringByAppendingPathComponent:@"display-ready.json"]] options:0 error:&error];
        if(!reference || ![reference[@"render_space"] isEqual:space] || ![reference[@"window_screen"] isEqual:screen.localizedName] || ![reference[@"patch_reference"] isKindOfClass:NSArray.class]) {fprintf(stderr,"External chart reference unavailable or incompatible\n");return 2;}
        if(![[NSData dataWithContentsOfFile:[source stringByAppendingPathComponent:@"display-profile.icc"]] isEqualToData:screen.colorSpace.ICCProfileData]) {fprintf(stderr,"External chart display profile changed\n");return 2;}
        for(NSString *key in @[@"patch_reference",@"window_frame",@"window_screen",@"render_image_space"])probe.metadata[key]=reference[key];
        if(![[NSFileManager defaultManager] copyItemAtPath:[source stringByAppendingPathComponent:@"source-render.png"] toPath:[out stringByAppendingPathComponent:@"source-render.png"] error:&error])return 2;
        probe.metadata[@"external_chart_source"]=source;
    } else probe.window=presentChart(screen,pattern,nil,space,out,probe.metadata);
    probe.ready=CFAbsoluteTimeGetCurrent()+3600.;
    [probe.session startRunning];
    if(CMFormatDescriptionGetMediaSubType(device.activeFormat.formatDescription)!=CMFormatDescriptionGetMediaSubType(chosen.formatDescription)) {
        [device unlockForConfiguration];[probe.session stopRunning];[probe.window close];fprintf(stderr,"AVFoundation changed the selected format\n");return 3;
    }
    probe.ready=CFAbsoluteTimeGetCurrent()+3.;
    probe.metadata[@"session_preset"]=probe.session.sessionPreset;
    probe.metadata[@"actual_active_subtype"]=fourcc(CMFormatDescriptionGetMediaSubType(device.activeFormat.formatDescription));
    if(probe.window && probe.window.screen!=screen) {fprintf(stderr,"Probe window is not on the target display\n");[device unlockForConfiguration];[probe.session stopRunning];[probe.window close];return 3;}
    CMVideoDimensions actual=CMVideoFormatDescriptionGetDimensions(device.activeFormat.formatDescription);
    probe.metadata[@"actual_active_size"]=@[@(actual.width),@(actual.height)];
    probe.metadata[@"actual_frame_duration"]=@(CMTimeGetSeconds(device.activeVideoMinFrameDuration));
    // Save source framebuffer in addition to the intended values; permission may be absent.
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)(2*NSEC_PER_SEC)),dispatch_get_main_queue(),^{
        CGDirectDisplayID did=[screen.deviceDescription[@"NSScreenNumber"] unsignedIntValue];
        if(!CGPreflightScreenCaptureAccess()) { @synchronized(probe.metadata) {probe.metadata[@"source_screenshot_error"]=@"Screen Recording permission is absent; source-render.png is the AppKit render, not a compositor/HDMI measurement";} return;}
        [SCShareableContent getShareableContentExcludingDesktopWindows:NO onScreenWindowsOnly:NO completionHandler:^(SCShareableContent *content,NSError *e) {
            SCDisplay *selected=nil; for(SCDisplay *d in content.displays) if(d.displayID==did) selected=d;
            if(!selected) { @synchronized(probe.metadata) {probe.metadata[@"source_screenshot_error"]=e.description ?: @"Display unavailable to ScreenCaptureKit";} return;}
            SCContentFilter *filter=[[SCContentFilter alloc] initWithDisplay:selected excludingWindows:@[]];
            SCStreamConfiguration *config=[SCStreamConfiguration new]; config.width=1920;config.height=1080;config.showsCursor=NO;
            config.pixelFormat=kCVPixelFormatType_32BGRA; // Default color space equals the captured display profile.
            [SCScreenshotManager captureImageWithFilter:filter configuration:config completionHandler:^(CGImageRef ref,NSError *e) {
                @synchronized(probe.metadata) { probe.metadata[@"source_screenshot_available"]=@(ref!=NULL);
                if(e) probe.metadata[@"source_screenshot_error"]=e.description;
                if(ref) {
                    probe.metadata[@"source_screenshot_space"]=screen.colorSpace.localizedName ?: @"display profile";
                    NSURL *url=[NSURL fileURLWithPath:[out stringByAppendingPathComponent:@"source-screen.png"]];
                    CGImageDestinationRef dest=CGImageDestinationCreateWithURL((__bridge CFURLRef)url,(__bridge CFStringRef)UTTypePNG.identifier,1,NULL);
                    CGImageDestinationAddImage(dest,ref,NULL);CGImageDestinationFinalize(dest);CFRelease(dest);
                } }
            }];
        }];
    });
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)(30*NSEC_PER_SEC)),dispatch_get_main_queue(),^{
        if(!probe.finished) {probe.finished=YES;probe.metadata[@"error"]=@"30-second acquisition timeout";jsonWrite(probe.metadata,[out stringByAppendingPathComponent:@"capture.json"]);[probe.session stopRunning];[probe.window close];fprintf(stderr,"Capture timeout\n");[NSApp terminate:nil];}
    });
    [NSApp run];[device unlockForConfiguration];return probe.count>=probe.wanted ? 0 : 3;
}}
