// Reversible timing selector for the MS2109 test display; changes display mode only.
#import <Cocoa/Cocoa.h>
#import <CoreGraphics/CoreGraphics.h>
#include <math.h>

static CGDirectDisplayID testDisplay(void) {
    CGDirectDisplayID found = 0;
    for (NSScreen *screen in NSScreen.screens) {
        if (![screen.localizedName isEqualToString:@"HDMI TO USB"]) continue;
        CGDirectDisplayID did = [screen.deviceDescription[@"NSScreenNumber"] unsignedIntValue];
        if (found) return 0;
        found = did;
    }
    return found;
}

static void printCurrent(CGDirectDisplayID did) {
    CGDisplayModeRef mode = CGDisplayCopyDisplayMode(did);
    if (!mode) { fprintf(stderr, "Cannot read current display mode\n"); exit(2); }
    printf("{\"display_id\":%u,\"width\":%zu,\"height\":%zu,\"refresh_hz\":%.3f,\"io_flags\":%llu}\n",
           did, CGDisplayModeGetPixelWidth(mode), CGDisplayModeGetPixelHeight(mode),
           CGDisplayModeGetRefreshRate(mode), (unsigned long long)CGDisplayModeGetIOFlags(mode));
    CGDisplayModeRelease(mode);
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        [NSApplication sharedApplication];
        if (argc < 2) {
            fprintf(stderr, "Usage: set_hdmi_output_mode list | set 1280 720 60 | set 1920 1080 60\n");
            return 2;
        }
        CGDirectDisplayID did = testDisplay();
        if (!did) { fprintf(stderr, "Unique HDMI TO USB display not found\n"); return 2; }
        NSString *verb = [NSString stringWithUTF8String:argv[1]];
        if ([verb isEqualToString:@"list"]) { printCurrent(did); return 0; }
        if (![verb isEqualToString:@"set"] || argc != 5) return 2;

        size_t width = (size_t)strtoul(argv[2], NULL, 10);
        size_t height = (size_t)strtoul(argv[3], NULL, 10);
        double refresh = strtod(argv[4], NULL);
        BOOL allowed = (width == 1280 && height == 720 && fabs(refresh - 60.0) < 0.1) ||
                       (width == 1920 && height == 1080 && fabs(refresh - 60.0) < 0.1);
        if (!allowed) { fprintf(stderr, "Only the tested 1280x720@60 and 1920x1080@60 modes are allowed\n"); return 2; }

        CFArrayRef modes = CGDisplayCopyAllDisplayModes(did, NULL);
        CGDisplayModeRef selected = NULL;
        for (CFIndex i = 0; i < CFArrayGetCount(modes); i++) {
            CGDisplayModeRef mode = (CGDisplayModeRef)CFArrayGetValueAtIndex(modes, i);
            if (CGDisplayModeGetPixelWidth(mode) != width || CGDisplayModeGetPixelHeight(mode) != height ||
                fabs(CGDisplayModeGetRefreshRate(mode) - refresh) >= 0.1) continue;
            if (!selected || CGDisplayModeGetIOFlags(mode) > CGDisplayModeGetIOFlags(selected)) selected = mode;
        }
        if (!selected) { CFRelease(modes); fprintf(stderr, "Requested mode is not advertised by HDMI TO USB\n"); return 2; }
        CGError result = CGDisplaySetDisplayMode(did, selected, NULL);
        CFRelease(modes);
        if (result != kCGErrorSuccess) { fprintf(stderr, "CGDisplaySetDisplayMode failed: %d\n", result); return 2; }
        [NSThread sleepForTimeInterval:0.8];
        if (CGDisplayPixelsWide(did) != width || CGDisplayPixelsHigh(did) != height) {
            fprintf(stderr, "Display did not enter the requested raster; current state: ");
            printCurrent(did);
            return 2;
        }
        printCurrent(did);
        return 0;
    }
}
