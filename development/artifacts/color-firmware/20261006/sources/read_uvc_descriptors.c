#include <libusb.h>
#include <stdio.h>
int main(void){libusb_context *ctx=NULL;libusb_device **list=NULL;if(libusb_init(&ctx)<0)return 2;ssize_t n=libusb_get_device_list(ctx,&list);int found=0;
 for(ssize_t i=0;i<n;i++){struct libusb_device_descriptor d;if(libusb_get_device_descriptor(list[i],&d)<0 || d.idVendor!=0x534d || d.idProduct!=0x2109)continue;struct libusb_config_descriptor *cfg=NULL;if(libusb_get_active_config_descriptor(list[i],&cfg)<0)continue;found++;
  printf("{\"vid\":21325,\"pid\":8457,\"configuration_total_bytes\":%u,\"color_records\":[",cfg->wTotalLength);int count=0;
  for(int j=0;j<cfg->bNumInterfaces;j++)for(int k=0;k<cfg->interface[j].num_altsetting;k++){const struct libusb_interface_descriptor *a=&cfg->interface[j].altsetting[k];if(a->bInterfaceClass!=14 || a->bInterfaceSubClass!=2)continue;unsigned fmt=0;for(int pos=0;pos+3<=a->extra_length;){const unsigned char *p=a->extra+pos;unsigned len=p[0];if(len<3 || pos+len>a->extra_length)break;if(p[1]==0x24 && (p[2]==4 || p[2]==6) && len>=4)fmt=p[3];if(p[1]==0x24 && p[2]==13 && len==6)printf("%s{\"interface\":%u,\"alt\":%u,\"format_index\":%u,\"primaries\":%u,\"transfer\":%u,\"matrix\":%u}",count++?",":"",a->bInterfaceNumber,a->bAlternateSetting,fmt,p[3],p[4],p[5]);pos+=len;}}
  printf("]}\n");libusb_free_config_descriptor(cfg);
 }libusb_free_device_list(list,1);libusb_exit(ctx);return found==1?0:1;}
