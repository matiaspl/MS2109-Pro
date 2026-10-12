#import <Cocoa/Cocoa.h>
#import <CommonCrypto/CommonDigest.h>
int main(){@autoreleasepool{
 NSMutableArray *rows=[NSMutableArray array];
 for(NSScreen *s in NSScreen.screens){
  if(![s.localizedName isEqual:@"HDMI TO USB"])continue;
  CGDirectDisplayID d=[s.deviceDescription[@"NSScreenNumber"] unsignedIntValue];
  NSMutableDictionary *r=[@{@"display_id":@(d),@"name":s.localizedName,@"pixels":@[@(CGDisplayPixelsWide(d)),@(CGDisplayPixelsHigh(d))],@"backing_scale":@(s.backingScaleFactor)} mutableCopy];
  CGColorSpaceRef c=CGDisplayCopyColorSpace(d);
  if(c){r[@"color_space"]=[(__bridge id)c description];CFDataRef data=CGColorSpaceCopyICCData(c);if(data){unsigned char digest[CC_SHA256_DIGEST_LENGTH];CC_SHA256(CFDataGetBytePtr(data),(CC_LONG)CFDataGetLength(data),digest);NSMutableString *h=[NSMutableString string];for(int i=0;i<CC_SHA256_DIGEST_LENGTH;i++)[h appendFormat:@"%02x",digest[i]];r[@"icc_sha256"]=h;r[@"icc_bytes"]=@(CFDataGetLength(data));r[@"icc_base64"]=[(__bridge NSData*)data base64EncodedStringWithOptions:0];CFRelease(data);}CGColorSpaceRelease(c);}
  CGDisplayModeRef mode=CGDisplayCopyDisplayMode(d);if(mode){r[@"refresh_hz"]=@(CGDisplayModeGetRefreshRate(mode));r[@"mode_id"]=@(CGDisplayModeGetIODisplayModeID(mode));r[@"mode_flags"]=@(CGDisplayModeGetIOFlags(mode));CGDisplayModeRelease(mode);}
  float rr[4096],gg[4096],bb[4096];uint32_t n=0;CGError e=CGGetDisplayTransferByTable(d,4096,rr,gg,bb,&n);r[@"lut_read_status"]=@(e);r[@"lut_entries"]=@(n);if(!e&&n>1){double max=0,sum=0;for(uint32_t i=0;i<n;i++){double ideal=(double)i/(n-1);float *channels[]={rr,gg,bb};for(int j=0;j<3;j++){double delta=channels[j][i]-ideal;sum+=delta*delta;if(fabs(delta)>max)max=fabs(delta);}}r[@"lut_identity_max_error"]=@(max);r[@"lut_identity_rms_error"]=@(sqrt(sum/(3*n)));}
  [rows addObject:r];
 }
 NSDictionary *result=@{@"displays":rows,@"limitation":@"Source display ICC and LUT metadata only; no screen pixels captured and no HDMI wire encoding measured"};NSData *data=[NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:nil];fwrite(data.bytes,1,data.length,stdout);puts("");return rows.count==1?0:2;
}}
