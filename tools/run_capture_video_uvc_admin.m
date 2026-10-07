// One-time macOS authorization for a fixed, reviewed MS2109 capture helper.
// The unprivileged chart presenter starts only after authentication succeeds.
#import <Foundation/Foundation.h>
#import <AppKit/AppKit.h>
#import <Security/Authorization.h>
#import <Security/AuthorizationTags.h>
#include <stdio.h>
#include <unistd.h>
static BOOL runProbe(NSString *binary,NSArray *arguments,NSString *logPath){
 NSTask *task=[NSTask new];task.executableURL=[NSURL fileURLWithPath:binary];task.arguments=arguments;
 [[NSFileManager defaultManager] createFileAtPath:logPath contents:[NSData data] attributes:nil];
 NSFileHandle *log=[NSFileHandle fileHandleForWritingAtPath:logPath];if(!log)return NO;
 task.standardOutput=log;task.standardError=log;NSError *error=nil;
 BOOL launched=[task launchAndReturnError:&error];if(!launched){fprintf(stderr,"Probe launch failed: %s\n",error.description.UTF8String);[log closeFile];return NO;}
 [task waitUntilExit];[log closeFile];return task.terminationStatus==0;
}
static BOOL runProbeList(NSString *binary,NSString *outputPath){
 NSTask *task=[NSTask new];task.executableURL=[NSURL fileURLWithPath:binary];task.arguments=@[@"list"];
 NSPipe *pipe=[NSPipe pipe];task.standardOutput=pipe;NSError *error=nil;
 if(![task launchAndReturnError:&error]){fprintf(stderr,"Probe inventory launch failed: %s\n",error.description.UTF8String);return NO;}
 NSData *data=[[pipe fileHandleForReading] readDataToEndOfFile];[task waitUntilExit];
 return task.terminationStatus==0 && [data writeToFile:outputPath options:NSDataWritingAtomic error:&error];
}
static NSDictionary *readChartState(NSString *source){
 NSString *path=[source stringByAppendingPathComponent:@"display-ready.json"];
 NSData *data=[NSData dataWithContentsOfFile:path];return data?[NSJSONSerialization JSONObjectWithData:data options:0 error:nil]:nil;
}
static BOOL chartStateReady(NSDictionary *state){
 return [state[@"target_display_available"] boolValue] && [state[@"display_profile_matches"] boolValue] && [state[@"window_screen"] isEqual:@"HDMI TO USB"];
}
static BOOL waitForChartOnTargetDisplay(NSString *source,int seconds,NSDictionary **stableState){
 NSInteger previousGeneration=-1;int stablePolls=0;
 for(int attempt=0;attempt<seconds*4;attempt++){
  NSDictionary *state=readChartState(source);
  if(chartStateReady(state)){
   NSInteger generation=[state[@"display_generation"] integerValue];
   if(generation==previousGeneration)stablePolls++;else{previousGeneration=generation;stablePolls=0;}
   if(stablePolls>=4){if(stableState)*stableState=state;return YES;}
  }else{previousGeneration=-1;stablePolls=0;}
  usleep(250000);
 }
 return NO;
}
int main(int argc,const char **argv){@autoreleasepool{
 if(argc!=6){fprintf(stderr,"Usage: admin-wrapper CAPTURE_BINARY DISPLAY_BINARY MANIFEST NEW_OUTPUT_DIRECTORY mjpeg|yuy2|both|quantization|contrast127|calibrate|qualify|same-handle|reconnect-cycles\n");return 2;}
 NSString *binary=@(argv[1]),*presenter=@(argv[2]),*manifest=@(argv[3]),*output=@(argv[4]),*mode=@(argv[5]);
 if(![@[@"mjpeg",@"yuy2",@"both",@"quantization",@"contrast127",@"calibrate",@"qualify",@"same-handle",@"reconnect-cycles"] containsObject:mode] || ![binary hasPrefix:@"/"] || ![presenter hasPrefix:@"/"] || ![output hasPrefix:@"/"] || [[NSFileManager defaultManager] fileExistsAtPath:output])return 2;
 BOOL calibrate=[mode isEqual:@"calibrate"];
 BOOL qualify=[mode isEqual:@"qualify"];
 BOOL sameHandle=[mode isEqual:@"same-handle"];
 BOOL reconnectCycles=[mode isEqual:@"reconnect-cycles"];
 BOOL quantization=[mode isEqual:@"quantization"];
 BOOL contrast127=[mode isEqual:@"contrast127"],multipleProfiles=quantization || contrast127;
 AuthorizationRef authorization=NULL;OSStatus status=AuthorizationCreate(NULL,kAuthorizationEmptyEnvironment,kAuthorizationFlagDefaults,&authorization);
 if(status!=errAuthorizationSuccess){fprintf(stderr,"AuthorizationCreate failed: %d\n",status);return 3;}
 AuthorizationItem item={kAuthorizationRightExecute,0,NULL,0};AuthorizationRights rights={1,&item};
 const char *prompt=calibrate ? "Calibrate the attached MS2109 (534d:2109) using original YUY2/MJPEG frames. Temporarily sweep brightness, contrast and saturation; restore original controls after each sample and UVC driver at completion. No firmware writes." : qualify ? "Capture original MS2109 YUY2/MJPEG USB payloads, then AVFoundation YUV and BGRA frames with control readbacks and display state. Restore controls and UVC driver after probes. No firmware writes." : sameHandle ? "Capture original MS2109 MJPEG then YUY2 frames on one persistent UVC handle. Read controls only; restore the UVC driver afterward. No picture-control or firmware writes." : reconnectCycles ? "Capture first post-reconnect MS2109 YUY2/MJPEG frames over three unplug/replug cycles. Read controls only; no picture-control or firmware writes. Restore the UVC driver after each capture." : contrast127 ? "Capture MS2109 RGB ramps at current controls and brightness UI 128 / contrast 127. Restore original controls and UVC driver afterward. No firmware writes." : quantization ? "Capture MS2109 RGB quantization ramps at current controls and brightness/contrast UI 127. Restore original controls and UVC driver afterward. No firmware writes." : "Capture original YUY2/MJPEG USB frames from the attached MS2109 (534d:2109). Temporary UVC driver access; no firmware or picture-control writes.";
 AuthorizationItem environmentItem={kAuthorizationEnvironmentPrompt,strlen(prompt),(void*)prompt,0};AuthorizationEnvironment environment={1,&environmentItem};
 fprintf(stderr,"Waiting for macOS administrator authentication for MS2109 raw USB capture.\n");fflush(stderr);
 status=AuthorizationCopyRights(authorization,&rights,&environment,kAuthorizationFlagInteractionAllowed|kAuthorizationFlagExtendRights|kAuthorizationFlagPreAuthorize,NULL);
 if(status!=errAuthorizationSuccess){fprintf(stderr,"Authentication unavailable/cancelled: %d\n",status);AuthorizationFree(authorization,kAuthorizationFlagDestroyRights);return 3;}
 if(qualify){
    NSFileManager *fm=[NSFileManager defaultManager];
    [fm createDirectoryAtPath:output withIntermediateDirectories:YES attributes:@{NSFilePosixPermissions:@0700} error:nil];
    NSString *raw=[output stringByAppendingPathComponent:@"raw"];
    [fm createDirectoryAtPath:raw withIntermediateDirectories:YES attributes:nil error:nil];
    NSString *claim=[raw stringByAppendingPathComponent:@"pre-chart-claim"];
    if(!runProbeList(presenter,[output stringByAppendingPathComponent:@"macos-state-before-pre-chart-claim.json"]))return 4;
    char *claimArgs[]={(char*)"yuy2",(char*)claim.UTF8String,(char*)"--get-cur-only",(char*)"--claim-only",NULL};FILE *claimPipe=NULL;
    #pragma clang diagnostic push
    #pragma clang diagnostic ignored "-Wdeprecated-declarations"
    status=AuthorizationExecuteWithPrivileges(authorization,binary.fileSystemRepresentation,kAuthorizationFlagDefaults,claimArgs,&claimPipe);
    #pragma clang diagnostic pop
    if(status==errAuthorizationSuccess && claimPipe){char buffer[2048];while(fgets(buffer,sizeof(buffer),claimPipe)){fputs(buffer,stdout);fflush(stdout);}fclose(claimPipe);}
    NSData *claimData=[NSData dataWithContentsOfFile:[claim stringByAppendingPathComponent:@"usb-capture.json"]];
    NSDictionary *claimInfo=claimData?[NSJSONSerialization JSONObjectWithData:claimData options:0 error:nil]:nil;
    if(status!=errAuthorizationSuccess || !claimInfo || [claimInfo[@"exit_code"] integerValue]!=0 || ![claimInfo[@"controls_restoration_ok"] boolValue]){fprintf(stderr,"Pre-chart USB claim trial failed\n");AuthorizationFree(authorization,kAuthorizationFlagDestroyRights);return 5;}
    if(!runProbeList(presenter,[output stringByAppendingPathComponent:@"macos-state-after-pre-chart-claim.json"])){AuthorizationFree(authorization,kAuthorizationFlagDestroyRights);return 4;}
 }
 NSString *source=[output stringByAppendingString:@"-source"];
 NSString *runTag=output.lastPathComponent;
 if(sameHandle || reconnectCycles){NSString *root=[[[output stringByDeletingLastPathComponent] stringByDeletingLastPathComponent] stringByStandardizingPath];source=[root stringByAppendingPathComponent:sameHandle?@"same-handle-chart":[NSString stringWithFormat:@"reconnect-chart-%@",runTag]];}
 NSTask *chart=[NSTask new];chart.executableURL=[NSURL fileURLWithPath:presenter];chart.arguments=@[@"--manifest",manifest,@"--output",source,@"--transport",@"display",@"--render-space",@"native",@"--seconds",(calibrate||qualify||sameHandle||reconnectCycles)?@"1000":multipleProfiles?@"90":@"30"];
 NSError *e=nil;if(![chart launchAndReturnError:&e]){fprintf(stderr,"Chart launch failed: %s\n",e.description.UTF8String);AuthorizationFree(authorization,kAuthorizationFlagDestroyRights);return 4;}
 NSString *ready=[source stringByAppendingPathComponent:@"display-ready.json"];
 for(int i=0;i<50 && ![[NSFileManager defaultManager] fileExistsAtPath:ready] && chart.isRunning;i++)usleep(100000);
 if(![[NSFileManager defaultManager] fileExistsAtPath:ready]){if(chart.isRunning)[chart terminate];AuthorizationFree(authorization,kAuthorizationFlagDestroyRights);return 4;}
 if(sameHandle){
    NSFileManager *fm=[NSFileManager defaultManager];
    [fm createDirectoryAtPath:output withIntermediateDirectories:YES attributes:@{NSFilePosixPermissions:@0700} error:nil];
    BOOL success=runProbeList(presenter,[output stringByAppendingPathComponent:@"macos-state-before.json"]);
    char *args[]={(char*)output.UTF8String,NULL};FILE *pipe=NULL;
    #pragma clang diagnostic push
    #pragma clang diagnostic ignored "-Wdeprecated-declarations"
    if(success)status=AuthorizationExecuteWithPrivileges(authorization,binary.fileSystemRepresentation,kAuthorizationFlagDefaults,args,&pipe);else status=-1;
    #pragma clang diagnostic pop
    if(status==errAuthorizationSuccess && pipe){char buffer[2048];while(fgets(buffer,sizeof(buffer),pipe)){fputs(buffer,stdout);fflush(stdout);}fclose(pipe);}
    for(NSString *format in @[@"mjpeg",@"yuy2"]){
      NSString *path=[[output stringByAppendingPathComponent:format] stringByAppendingPathComponent:@"usb-capture.json"];
      NSData *data=[NSData dataWithContentsOfFile:path];NSDictionary *meta=data?[NSJSONSerialization JSONObjectWithData:data options:0 error:nil]:nil;
      if(status!=errAuthorizationSuccess || !meta || [meta[@"exit_code"] integerValue]!=0 || ![meta[@"controls_restoration_ok"] boolValue])success=NO;
    }
    if(!runProbeList(presenter,[output stringByAppendingPathComponent:@"macos-state-after.json"]))success=NO;
    for(NSString *name in @[@"display-ready.json",@"display-profile.icc",@"source-render.png"]){NSString *from=[source stringByAppendingPathComponent:name],*to=[output stringByAppendingPathComponent:name];if([fm fileExistsAtPath:from]) [fm copyItemAtPath:from toPath:to error:nil];}
    if(chart.isRunning)[chart terminate];[chart waitUntilExit];AuthorizationFree(authorization,kAuthorizationFlagDestroyRights);
    if(!success)return 5;
    fprintf(stderr,"Same-handle MJPEG-to-YUY2 capture completed; controls were read only and the UVC driver was restored.\n");return 0;
 }
 if(reconnectCycles){
    NSFileManager *fm=[NSFileManager defaultManager];
    NSString *root=[[[output stringByDeletingLastPathComponent] stringByDeletingLastPathComponent] stringByStandardizingPath];
    NSString *raw=[root stringByAppendingPathComponent:@"raw"];
    [fm createDirectoryAtPath:raw withIntermediateDirectories:YES attributes:@{NSFilePosixPermissions:@0700} error:nil];
    [NSApplication sharedApplication];[NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];[NSApp activateIgnoringOtherApps:YES];
    BOOL success=YES;int completed=0;
    for(int cycle=1;cycle<=3 && success;cycle++){
      NSAlert *alert=[NSAlert new];alert.messageText=[NSString stringWithFormat:@"Reconnect cycle %d of 3",cycle];
      alert.informativeText=@"Keep the 1920×1080 HDMI source connected. Unplug the grabber's USB cable, reconnect it, wait for macOS to recognize the MS2109, then choose Capture first frames. The chart hides while its target display is disconnected and returns there before capture; it will not cover the main screen. This capture reads controls only and will not change picture controls or firmware.";
      [alert addButtonWithTitle:@"Capture first frames"];[alert addButtonWithTitle:@"Stop here"];
      if([alert runModal]!=NSAlertFirstButtonReturn){fprintf(stderr,"Reconnect qualification stopped by user after %d complete cycle(s).\n",completed);success=NO;break;}
      NSString *trial=[raw stringByAppendingPathComponent:[NSString stringWithFormat:@"%@-cycle-%d",runTag,cycle]];
      NSString *stateBefore=[root stringByAppendingPathComponent:[NSString stringWithFormat:@"%@-cycle-%d-macos-state-before.json",runTag,cycle]];
      NSDictionary *stableState=nil;
      if(!waitForChartOnTargetDisplay(source,45,&stableState)){fprintf(stderr,"Reconnect cycle %d stopped: the 1920x1080 chart display/profile did not return and stabilize within 45 seconds; no frames were captured for this cycle.\n",cycle);success=NO;break;}
      if(![fm createDirectoryAtPath:trial withIntermediateDirectories:NO attributes:@{NSFilePosixPermissions:@0700} error:nil] || !runProbeList(presenter,stateBefore)){fprintf(stderr,"Unable to initialize reconnect cycle %d\n",cycle);success=NO;break;}
      for(NSString *format in @[@"yuy2",@"mjpeg"]){
        stableState=nil;
        if(!waitForChartOnTargetDisplay(source,45,&stableState)){fprintf(stderr,"Reconnect cycle %d %s stopped: chart display/profile did not stabilize before capture.\n",cycle,format.UTF8String);success=NO;break;}
        NSString *formatState=[trial stringByAppendingPathComponent:[NSString stringWithFormat:@"%@-display-ready.json",format]];
        NSString *formatProfile=[trial stringByAppendingPathComponent:[NSString stringWithFormat:@"%@-display-profile.icc",format]];
        NSString *formatRender=[trial stringByAppendingPathComponent:[NSString stringWithFormat:@"%@-source-render.png",format]];
        BOOL referenceSaved=[fm copyItemAtPath:[source stringByAppendingPathComponent:@"display-ready.json"] toPath:formatState error:nil] &&
                            [fm copyItemAtPath:[source stringByAppendingPathComponent:@"display-profile.icc"] toPath:formatProfile error:nil] &&
                            [fm copyItemAtPath:[source stringByAppendingPathComponent:@"source-render.png"] toPath:formatRender error:nil];
        if(!referenceSaved){fprintf(stderr,"Reconnect cycle %d %s reference snapshot failed\n",cycle,format.UTF8String);success=NO;break;}
        NSInteger generationBefore=[stableState[@"display_generation"] integerValue];
        NSString *directory=[trial stringByAppendingPathComponent:format];
        char *args[]={(char*)format.UTF8String,(char*)directory.UTF8String,(char*)"--get-cur-only",(char*)"--first-frames",NULL};FILE *pipe=NULL;
        #pragma clang diagnostic push
        #pragma clang diagnostic ignored "-Wdeprecated-declarations"
        status=AuthorizationExecuteWithPrivileges(authorization,binary.fileSystemRepresentation,kAuthorizationFlagDefaults,args,&pipe);
        #pragma clang diagnostic pop
        if(status==errAuthorizationSuccess && pipe){char buffer[2048];while(fgets(buffer,sizeof(buffer),pipe)){fputs(buffer,stdout);fflush(stdout);}fclose(pipe);}
        NSString *metaPath=[directory stringByAppendingPathComponent:@"usb-capture.json"];
        NSDictionary *meta=nil;NSData *data=[NSData dataWithContentsOfFile:metaPath];if(data)meta=[NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
        NSData *requestData=[NSData dataWithContentsOfFile:[directory stringByAppendingPathComponent:@"control-requests.jsonl"]];
        NSString *requests=requestData?[[NSString alloc] initWithData:requestData encoding:NSUTF8StringEncoding]:@"";
        NSDictionary *afterCapture=readChartState(source);
        if(status!=errAuthorizationSuccess || !meta || [meta[@"exit_code"] integerValue]!=0 || ![meta[@"controls_restoration_ok"] boolValue] || [requests containsString:@"\"direction\":\"OUT\""] || [meta[@"frames_captured"] unsignedIntegerValue]!=8 || !chartStateReady(afterCapture) || [afterCapture[@"display_generation"] integerValue]!=generationBefore){fprintf(stderr,"Reconnect cycle %d %s capture failed read-only, eight-frame, or stable-chart checks\n",cycle,format.UTF8String);success=NO;break;}
      }
      if(!runProbeList(presenter,[root stringByAppendingPathComponent:[NSString stringWithFormat:@"%@-cycle-%d-macos-state-after.json",runTag,cycle]]))success=NO;
      if(success){completed++;fprintf(stderr,"Reconnect cycle %d captured YUY2 and MJPEG first frames with GET_CUR only.\n",cycle);}
    }
    for(NSString *name in @[@"display-ready.json",@"display-profile.icc",@"source-render.png"]){NSString *from=[source stringByAppendingPathComponent:name],*to=[root stringByAppendingPathComponent:[NSString stringWithFormat:@"%@-%@",runTag,name]];if([fm fileExistsAtPath:from] && ![fm fileExistsAtPath:to])[fm copyItemAtPath:from toPath:to error:nil];}
    if(chart.isRunning)[chart terminate];[chart waitUntilExit];AuthorizationFree(authorization,kAuthorizationFlagDestroyRights);
    fprintf(stderr,"Reconnect cycle result: %d of 3 complete.\n",completed);return success && completed==3?0:5;
 }
 if(calibrate){
    BOOL created=[[NSFileManager defaultManager] createDirectoryAtPath:output withIntermediateDirectories:NO attributes:@{NSFilePosixPermissions:@0700} error:&e];
    FILE *pipe=NULL;char *args[]={(char*)"calibrate",(char*)output.UTF8String,NULL};
    #pragma clang diagnostic push
    #pragma clang diagnostic ignored "-Wdeprecated-declarations"
    if(created)status=AuthorizationExecuteWithPrivileges(authorization,binary.fileSystemRepresentation,kAuthorizationFlagDefaults,args,&pipe);else status=-1;
    #pragma clang diagnostic pop
    if(status==errAuthorizationSuccess && pipe){char buffer[2048];while(fgets(buffer,sizeof(buffer),pipe)){fputs(buffer,stdout);fflush(stdout);}fclose(pipe);}
    NSData *data=[NSData dataWithContentsOfFile:[output stringByAppendingPathComponent:@"session.json"]];
    NSDictionary *metadata=data?[NSJSONSerialization JSONObjectWithData:data options:0 error:nil]:nil;
    BOOL success=status==errAuthorizationSuccess && metadata && [metadata[@"exit_code"] integerValue]==0 && [metadata[@"controls_restoration_ok"] boolValue];
    if(chart.isRunning)[chart terminate];[chart waitUntilExit];AuthorizationFree(authorization,kAuthorizationFlagDestroyRights);
    return success?0:5;
 }
 if(qualify){
    NSFileManager *fm=[NSFileManager defaultManager];
    [fm createDirectoryAtPath:output withIntermediateDirectories:YES attributes:@{NSFilePosixPermissions:@0700} error:nil];
    NSString *raw=[output stringByAppendingPathComponent:@"raw"];
    NSString *avf=[output stringByAppendingPathComponent:@"avfoundation"];
    [fm createDirectoryAtPath:raw withIntermediateDirectories:YES attributes:nil error:nil];
    [fm createDirectoryAtPath:avf withIntermediateDirectories:YES attributes:nil error:nil];
    BOOL success=YES;
    NSArray *trials=@[
      @{ @"name":@"all-getters-mjpeg-first", @"options":@[], @"formats":@[@"mjpeg",@"yuy2"] },
      @{ @"name":@"get-cur-only-mjpeg-first", @"options":@[@"--get-cur-only"], @"formats":@[@"mjpeg",@"yuy2"] },
      @{ @"name":@"reapply-current-mjpeg-first", @"options":@[@"--get-cur-only",@"--reapply-current"], @"formats":@[@"mjpeg",@"yuy2"] },
      @{ @"name":@"all-getters-yuy2-first", @"options":@[], @"formats":@[@"yuy2",@"mjpeg"] }
    ];
    for(NSDictionary *trial in trials){
      NSString *trialDir=[raw stringByAppendingPathComponent:trial[@"name"]];[fm createDirectoryAtPath:trialDir withIntermediateDirectories:YES attributes:nil error:nil];
      for(NSString *current in trial[@"formats"]){
        NSString *directory=[trialDir stringByAppendingPathComponent:current];
        NSMutableArray *opts=[NSMutableArray arrayWithArray:trial[@"options"]];char *args[6]={0};args[0]=(char*)current.UTF8String;args[1]=(char*)directory.UTF8String;
        for(NSUInteger i=0;i<opts.count;i++)args[i+2]=(char*)[opts[i] UTF8String];args[opts.count+2]=NULL;
        FILE *pipe=NULL;
        #pragma clang diagnostic push
        #pragma clang diagnostic ignored "-Wdeprecated-declarations"
        status=AuthorizationExecuteWithPrivileges(authorization,binary.fileSystemRepresentation,kAuthorizationFlagDefaults,args,&pipe);
        #pragma clang diagnostic pop
        if(status==errAuthorizationSuccess && pipe){char buffer[2048];while(fgets(buffer,sizeof(buffer),pipe)){fputs(buffer,stdout);fflush(stdout);}fclose(pipe);}
        NSData *data=[NSData dataWithContentsOfFile:[directory stringByAppendingPathComponent:@"usb-capture.json"]];
        NSDictionary *metadata=data?[NSJSONSerialization JSONObjectWithData:data options:0 error:nil]:nil;
        if(status!=errAuthorizationSuccess || !metadata || [metadata[@"exit_code"] integerValue]!=0 || ![metadata[@"controls_restoration_ok"] boolValue]){fprintf(stderr,"Qualification raw trial failed: %s/%s\n",[[trial objectForKey:@"name"] description].UTF8String,current.UTF8String);success=NO;break;}
      }
      if(!success)break;
    }
    if(success && !runProbeList(presenter,[output stringByAppendingPathComponent:@"macos-state-before-avfoundation.json"]))success=NO;
    for(NSString *pixel in @[@"yuv",@"bgra"]){
      if(!success)break;
      NSString *directory=[avf stringByAppendingPathComponent:pixel];
      NSString *logPath=[avf stringByAppendingFormat:@"/%@.log",pixel];
      NSArray *arguments=@[@"--manifest",manifest,@"--output",directory,@"--render-space",@"native",@"--transport",@"yuv",@"--frames",@"8",@"--pixel-format",pixel,@"--observe-source",source];
      if(!runProbe(presenter,arguments,logPath)){fprintf(stderr,"AVFoundation %s capture failed\n",pixel.UTF8String);success=NO;break;}
    }
    if(!runProbeList(presenter,[output stringByAppendingPathComponent:@"macos-state-after-avfoundation.json"]))success=NO;
    if(chart.isRunning)[chart terminate];[chart waitUntilExit];AuthorizationFree(authorization,kAuthorizationFlagDestroyRights);
    if(!success)return 5;
    fprintf(stderr,"Qualification capture complete. Chart preceded USB claims; controls read back/restored for every raw session; AVFoundation YUV/BGRA captured after UVC restoration.\n");return 0;
 }
 NSArray *modes=([mode isEqual:@"both"] || multipleProfiles) ? @[@"mjpeg",@"yuy2"] : @[mode];
 NSArray *profiles=contrast127 ? @[@"current",@"ui128c127"] : quantization ? @[@"current",@"ui127"] : @[@"current"];
 if([mode isEqual:@"both"] || multipleProfiles) [[NSFileManager defaultManager] createDirectoryAtPath:output withIntermediateDirectories:YES attributes:nil error:nil];
 BOOL success=YES;
 for(NSString *profile in profiles) {
 NSString *base=multipleProfiles ? [output stringByAppendingPathComponent:profile] : output;
 if(multipleProfiles)[[NSFileManager defaultManager] createDirectoryAtPath:base withIntermediateDirectories:YES attributes:nil error:nil];
 for(NSString *current in modes) {
    NSString *directory=([mode isEqual:@"both"] || multipleProfiles) ? [base stringByAppendingPathComponent:current] : output;
    char *option=[profile isEqual:@"ui127"]?(char*)"--ui127":[profile isEqual:@"ui128c127"]?(char*)"--b128-c127":NULL;
    char *args[]={(char*)current.UTF8String,(char*)directory.UTF8String,option,NULL};FILE *pipe=NULL;
    #pragma clang diagnostic push
    #pragma clang diagnostic ignored "-Wdeprecated-declarations"
    status=AuthorizationExecuteWithPrivileges(authorization,binary.fileSystemRepresentation,kAuthorizationFlagDefaults,args,&pipe);
    #pragma clang diagnostic pop
    if(status==errAuthorizationSuccess && pipe){char buffer[2048];while(fgets(buffer,sizeof(buffer),pipe))fputs(buffer,stdout);fclose(pipe);}
    NSData *data=[NSData dataWithContentsOfFile:[directory stringByAppendingPathComponent:@"usb-capture.json"]];
    NSDictionary *metadata=data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
    if(status!=errAuthorizationSuccess || !metadata || [metadata[@"exit_code"] integerValue]!=0 || (metadata[@"controls_restoration_ok"] && ![metadata[@"controls_restoration_ok"] boolValue])){fprintf(stderr,"Raw capture incomplete: authorization=%d\n",status);success=NO;break;}
 }
 if(!success)break;
 }
 if(chart.isRunning)[chart terminate];[chart waitUntilExit];
 AuthorizationFree(authorization,kAuthorizationFlagDestroyRights);
 if(!success)return 5;
 fprintf(stderr,"Original USB %s capture complete; chart closed.\n",mode.UTF8String);return 0;
}}
