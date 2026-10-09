// One-time macOS authorization for a fixed, reviewed MS2109 capture helper.
// The unprivileged chart presenter starts only after authentication succeeds.
#import <Foundation/Foundation.h>
#import <Security/Authorization.h>
#import <Security/AuthorizationTags.h>
#include <stdio.h>
#include <unistd.h>
int main(int argc,const char **argv){@autoreleasepool{
 if(argc!=6){fprintf(stderr,"Usage: admin-wrapper CAPTURE_BINARY DISPLAY_BINARY MANIFEST NEW_OUTPUT_DIRECTORY mjpeg|yuy2|both|quantization|contrast127\n");return 2;}
 NSString *binary=@(argv[1]),*presenter=@(argv[2]),*manifest=@(argv[3]),*output=@(argv[4]),*mode=@(argv[5]);
 if(![@[@"mjpeg",@"yuy2",@"both",@"quantization",@"contrast127"] containsObject:mode] || ![binary hasPrefix:@"/"] || ![presenter hasPrefix:@"/"] || ![output hasPrefix:@"/"] || [[NSFileManager defaultManager] fileExistsAtPath:output])return 2;
 BOOL quantization=[mode isEqual:@"quantization"];
 BOOL contrast127=[mode isEqual:@"contrast127"],multipleProfiles=quantization || contrast127;
 AuthorizationRef authorization=NULL;OSStatus status=AuthorizationCreate(NULL,kAuthorizationEmptyEnvironment,kAuthorizationFlagDefaults,&authorization);
 if(status!=errAuthorizationSuccess)return 3;
 AuthorizationItem item={kAuthorizationRightExecute,0,NULL,0};AuthorizationRights rights={1,&item};
 const char *prompt=contrast127 ? "Capture MS2109 RGB ramps at current controls and brightness UI 128 / contrast 127. Restore original controls and UVC driver afterward. No firmware writes." : quantization ? "Capture MS2109 RGB quantization ramps at current controls and brightness/contrast UI 127. Restore original controls and UVC driver afterward. No firmware writes." : "Capture original YUY2/MJPEG USB frames from the attached MS2109 (534d:2109). Temporary UVC driver access; no firmware or picture-control writes.";
 AuthorizationItem environmentItem={kAuthorizationEnvironmentPrompt,strlen(prompt),(void*)prompt,0};AuthorizationEnvironment environment={1,&environmentItem};
 fprintf(stderr,"Waiting for macOS administrator authentication for MS2109 raw USB capture.\n");fflush(stderr);
 status=AuthorizationCopyRights(authorization,&rights,&environment,kAuthorizationFlagInteractionAllowed|kAuthorizationFlagExtendRights|kAuthorizationFlagPreAuthorize,NULL);
 if(status!=errAuthorizationSuccess){fprintf(stderr,"Authentication unavailable/cancelled: %d\n",status);AuthorizationFree(authorization,kAuthorizationFlagDestroyRights);return 3;}
 NSString *source=[output stringByAppendingString:@"-source"];
 NSTask *chart=[NSTask new];chart.executableURL=[NSURL fileURLWithPath:presenter];chart.arguments=@[@"--manifest",manifest,@"--output",source,@"--transport",@"display",@"--render-space",@"native",@"--seconds",multipleProfiles?@"90":@"30"];
 NSError *e=nil;if(![chart launchAndReturnError:&e]){fprintf(stderr,"Chart launch failed: %s\n",e.description.UTF8String);AuthorizationFree(authorization,kAuthorizationFlagDestroyRights);return 4;}
 NSString *ready=[source stringByAppendingPathComponent:@"display-ready.json"];
 for(int i=0;i<50 && ![[NSFileManager defaultManager] fileExistsAtPath:ready] && chart.isRunning;i++)usleep(100000);
 if(![[NSFileManager defaultManager] fileExistsAtPath:ready]){if(chart.isRunning)[chart terminate];AuthorizationFree(authorization,kAuthorizationFlagDestroyRights);return 4;}
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
