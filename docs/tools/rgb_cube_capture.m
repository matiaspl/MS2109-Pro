// Display a deterministic full RGB cube and save raw packed YUY2 frames.
// This program changes no firmware or UVC picture controls.
#import <Cocoa/Cocoa.h>
#import <AVFoundation/AVFoundation.h>
#import <CoreVideo/CoreVideo.h>
#import <CoreMedia/CoreMedia.h>

static void jsonWrite(id obj, NSString *path) {
    NSError *error = nil;
    NSData *data = [NSJSONSerialization dataWithJSONObject:obj options:NSJSONWritingPrettyPrinted error:&error];
    if (!data || ![data writeToFile:path options:NSDataWritingAtomic error:&error]) {
        fprintf(stderr, "JSON write failed: %s\n", error.description.UTF8String);
        exit(2);
    }
}

@interface RGBPageView : NSView
@property NSImage *pageImage;
@end
@implementation RGBPageView
-(BOOL)isFlipped { return YES; }
-(void)drawRect:(NSRect)dirty {
    [[NSColor blackColor] setFill]; NSRectFill(self.bounds);
    [self.pageImage drawInRect:self.bounds fromRect:NSZeroRect operation:NSCompositingOperationCopy fraction:1.0];
}
@end

@interface CubeProbe : NSObject <AVCaptureVideoDataOutputSampleBufferDelegate>
@property AVCaptureSession *session;
@property NSWindow *window;
@property RGBPageView *view;
@property NSString *output;
@property NSString *pagesPath;
@property NSMutableDictionary *metadata;
@property NSArray *pageRecords;
@property NSInteger pageIndex;
@property NSInteger pageFrame;
@property NSInteger framesPerPage;
@property NSInteger count;
@property CFAbsoluteTime ready;
@property BOOL transitioning;
@property BOOL finished;
@end

@implementation CubeProbe
-(void)finishWithError:(NSString *)message {
    self.finished = YES;
    if (message) self.metadata[@"error"] = message;
    self.metadata[@"exit_code"] = @(message ? 1 : 0);
    jsonWrite(self.metadata, [self.output stringByAppendingPathComponent:@"capture.json"]);
    dispatch_async(dispatch_get_main_queue(), ^{
        [self.session stopRunning]; [self.window close]; [NSApp terminate:nil];
    });
}
-(void)advancePage {
    if (self.pageIndex + 1 >= self.pageRecords.count) { [self finishWithError:nil]; return; }
    self.pageIndex++;
    NSDictionary *record = self.pageRecords[self.pageIndex];
    NSString *path = [self.pagesPath stringByAppendingPathComponent:record[@"file"]];
    NSImage *image = [[NSImage alloc] initWithContentsOfFile:path];
    if (!image) { [self finishWithError:[NSString stringWithFormat:@"Cannot load page image %@", path]]; return; }
    self.view.pageImage = image;
    [self.view setNeedsDisplay:YES]; [self.view display];
    self.pageFrame = 0;
    self.ready = CFAbsoluteTimeGetCurrent() + 2.0;
    self.transitioning = NO;
    fprintf(stderr, "Displayed RGB cube page %ld/%lu\n", (long)self.pageIndex + 1, (unsigned long)self.pageRecords.count);
}
-(void)captureOutput:(AVCaptureOutput *)output didOutputSampleBuffer:(CMSampleBufferRef)sample fromConnection:(AVCaptureConnection *)connection {
    if (self.finished || self.transitioning || CFAbsoluteTimeGetCurrent() < self.ready) return;
    CVPixelBufferRef buffer = CMSampleBufferGetImageBuffer(sample);
    if (!buffer) return;
    CVPixelBufferLockBaseAddress(buffer, kCVPixelBufferLock_ReadOnly);
    size_t width = CVPixelBufferGetWidth(buffer), height = CVPixelBufferGetHeight(buffer);
    size_t stride = CVPixelBufferGetBytesPerRow(buffer);
    OSType type = CVPixelBufferGetPixelFormatType(buffer);
    if (width != 1920 || height != 1080 || type != kCVPixelFormatType_422YpCbCr8_yuvs) {
        CVPixelBufferUnlockBaseAddress(buffer, kCVPixelBufferLock_ReadOnly);
        [self finishWithError:[NSString stringWithFormat:@"Unexpected capture frame %zux%zu format %08x", width, height, (unsigned)type]];
        return;
    }
    NSMutableData *data = [NSMutableData dataWithLength:width * height * 2];
    for (size_t y = 0; y < height; y++)
        memcpy((uint8_t *)data.mutableBytes + y * width * 2,
               (uint8_t *)CVPixelBufferGetBaseAddress(buffer) + y * stride, width * 2);
    CVPixelBufferUnlockBaseAddress(buffer, kCVPixelBufferLock_ReadOnly);

    NSInteger page = self.pageIndex, pageFrame = self.pageFrame;
    NSString *name = [NSString stringWithFormat:@"page-%02ld-frame-%02ld.yuvs", (long)page, (long)pageFrame];
    NSError *error = nil;
    if (![data writeToFile:[self.output stringByAppendingPathComponent:name] options:NSDataWritingAtomic error:&error]) {
        [self finishWithError:[NSString stringWithFormat:@"Frame save failed: %@", error]]; return;
    }
    NSDictionary *entry = @{@"page":@(page), @"page_frame":@(pageFrame), @"file":name,
        @"width":@(width), @"height":@(height), @"pixel_format":@"yuvs",
        @"pts_seconds":@(CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(sample)))};
    [self.metadata[@"frames"] addObject:entry];
    self.count++; self.pageFrame++;
    fprintf(stderr, "Captured page %ld frame %ld/%ld (%ld total)\n", (long)page,
            (long)self.pageFrame, (long)self.framesPerPage, (long)self.count);
    if (self.pageFrame >= self.framesPerPage) {
        self.transitioning = YES;
        dispatch_async(dispatch_get_main_queue(), ^{ [self advancePage]; });
    }
}
@end

static NSString *argValue(int argc, const char **argv, NSString *key) {
    for (int i = 1; i + 1 < argc; i++) if ([[@(argv[i]) lowercaseString] isEqual:key]) return @(argv[i+1]);
    return nil;
}

int main(int argc, const char **argv) { @autoreleasepool {
    NSString *pagesPath = argValue(argc, argv, @"--pages");
    NSString *output = argValue(argc, argv, @"--output");
    if (!pagesPath || !output) { fprintf(stderr, "Usage: rgb_cube_capture --pages DIRECTORY --output NEW_DIRECTORY\n"); return 2; }
    NSFileManager *fm = NSFileManager.defaultManager;
    if ([fm fileExistsAtPath:output]) { fprintf(stderr, "Refusing to overwrite output directory\n"); return 2; }
    NSError *error = nil;
    NSDictionary *source = [NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:[pagesPath stringByAppendingPathComponent:@"rgb-cube.json"]] options:0 error:&error];
    NSArray *pageRecords = source[@"pages"];
    if (!pageRecords || pageRecords.count != 9 || [source[@"unique_input_rgb_triplets"] integerValue] != (1 << 24)) {
        fprintf(stderr, "Invalid RGB cube manifest: %s\n", error.description.UTF8String ?: "unexpected schema"); return 2;
    }
    if (![fm createDirectoryAtPath:output withIntermediateDirectories:YES attributes:nil error:&error]) {
        fprintf(stderr, "Cannot create output: %s\n", error.description.UTF8String); return 2;
    }
    [fm copyItemAtPath:[pagesPath stringByAppendingPathComponent:@"rgb-cube.json"]
                toPath:[output stringByAppendingPathComponent:@"rgb-cube.json"] error:nil];

    [NSApplication sharedApplication]; [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
    NSScreen *screen = nil;
    for (NSScreen *candidate in NSScreen.screens) {
        CGDirectDisplayID display = [candidate.deviceDescription[@"NSScreenNumber"] unsignedIntValue];
        if (display != CGMainDisplayID() && CGDisplayPixelsWide(display) == 1920 &&
            CGDisplayPixelsHigh(display) == 1080 && [candidate.localizedName isEqual:@"HDMI TO USB"]) {
            if (screen) { fprintf(stderr, "Ambiguous HDMI TO USB display\n"); return 2; }
            screen = candidate;
        }
    }
    if (!screen || screen.frame.size.width != 1920 || screen.frame.size.height != 1080) {
        fprintf(stderr, "Expected 1920x1080 HDMI TO USB display at 1:1 scale\n"); return 2;
    }
    AVCaptureDevice *device = nil;
    for (AVCaptureDevice *candidate in [AVCaptureDevice devicesWithMediaType:AVMediaTypeVideo])
        if ([candidate.localizedName isEqual:@"usb video"]) {
            if (device) { fprintf(stderr, "Ambiguous usb video capture device\n"); return 2; }
            device = candidate;
        }
    if (!device) { fprintf(stderr, "usb video capture device not found\n"); return 2; }

    AVCaptureDeviceFormat *chosen = nil; double fps = 0;
    for (AVCaptureDeviceFormat *format in device.formats) {
        CMVideoDimensions dim = CMVideoFormatDescriptionGetDimensions(format.formatDescription);
        OSType subtype = CMFormatDescriptionGetMediaSubType(format.formatDescription);
        if (dim.width != 1920 || dim.height != 1080 || subtype != kCVPixelFormatType_422YpCbCr8_yuvs) continue;
        for (AVFrameRateRange *range in format.videoSupportedFrameRateRanges)
            if (range.maxFrameRate > fps) { chosen = format; fps = range.maxFrameRate; }
    }
    if (!chosen) { fprintf(stderr, "No 1080p packed YUY2 capture mode\n"); return 2; }
    AVCaptureDeviceInput *input = [AVCaptureDeviceInput deviceInputWithDevice:device error:&error];
    if (!input) { fprintf(stderr, "AVFoundation input failed: %s\n", error.description.UTF8String); return 2; }

    CubeProbe *probe = [CubeProbe new]; probe.output = output; probe.pagesPath = pagesPath;
    probe.pageRecords = pageRecords; probe.pageIndex = 0; probe.pageFrame = 0; probe.framesPerPage = 2;
    probe.metadata = [@{@"capture_device":device.localizedName, @"capture_device_id":device.uniqueID,
        @"width":@1920, @"height":@1080, @"pixel_format":@"yuvs", @"transport":@"AVFoundation packed YUY2",
        @"fps":@(fps), @"frames_per_page":@(probe.framesPerPage), @"settle_seconds_per_page":@2,
        @"frames":[NSMutableArray array], @"screen_name":screen.localizedName,
        @"display_profile":screen.colorSpace.localizedName ?: @"unknown",
        @"screen_capture_permission_used":@NO} mutableCopy];

    probe.window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0,0,1920,1080)
        styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:NO screen:screen];
    probe.window.releasedWhenClosed = NO; probe.window.opaque = YES; probe.window.level = NSStatusWindowLevel + 1;
    probe.window.collectionBehavior = NSWindowCollectionBehaviorCanJoinAllSpaces;
    probe.view = [[RGBPageView alloc] initWithFrame:NSMakeRect(0,0,1920,1080)];
    probe.view.pageImage = [[NSImage alloc] initWithContentsOfFile:[pagesPath stringByAppendingPathComponent:pageRecords[0][@"file"]]];
    if (!probe.view.pageImage) { fprintf(stderr, "Cannot load first RGB page\n"); return 2; }
    probe.window.contentView = probe.view; [probe.window orderFrontRegardless];
    [probe.window setFrame:screen.frame display:YES]; [probe.view display];

    probe.session = [AVCaptureSession new];
    if (![probe.session canAddInput:input]) return 2; [probe.session addInput:input];
    if (![device lockForConfiguration:&error]) { fprintf(stderr, "Format lock failed: %s\n", error.description.UTF8String); return 2; }
    device.activeFormat = chosen;
    for (AVFrameRateRange *range in chosen.videoSupportedFrameRateRanges)
        if (fabs(range.maxFrameRate - fps) < 0.001) device.activeVideoMinFrameDuration = range.minFrameDuration;
    device.activeVideoMaxFrameDuration = device.activeVideoMinFrameDuration;
    AVCaptureVideoDataOutput *videoOutput = [AVCaptureVideoDataOutput new];
    videoOutput.alwaysDiscardsLateVideoFrames = YES;
    videoOutput.videoSettings = @{(id)kCVPixelBufferPixelFormatTypeKey:@(kCVPixelFormatType_422YpCbCr8_yuvs)};
    [videoOutput setSampleBufferDelegate:probe queue:dispatch_queue_create("rgb-cube-capture", DISPATCH_QUEUE_SERIAL)];
    if (![probe.session canAddOutput:videoOutput]) return 2; [probe.session addOutput:videoOutput];
    probe.ready = CFAbsoluteTimeGetCurrent() + 3.0;
    if (probe.window.screen != screen) { fprintf(stderr, "RGB sweep is not on target display\n"); return 2; }
    [probe.session startRunning];
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 180 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
        if (!probe.finished) [probe finishWithError:@"Timed out during RGB cube capture"];
    });
    [NSApp run];
    [device unlockForConfiguration];
    return [probe.metadata[@"exit_code"] intValue];
}}
