/* Preserve original UVC YUY2 or MJPEG frame payloads, without color conversion.
 * Optional --ui127 or --b128-c127 temporarily tests explicit UI controls.
 * Their previous UVC values are read, journaled, restored, and checked.
 * No firmware or EEPROM writes.
 * libuvc may temporarily detach/re-attach the macOS UVC driver to claim USB.
 */
#include <libuvc/libuvc.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <pthread.h>
#include <sys/stat.h>
#include <errno.h>

struct capture {const char *out,*mode; FILE *json; unsigned count,wanted,skipped;int failed;double ready;pthread_mutex_t lock;pthread_cond_t changed;};
static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec*1e-9;}
struct controls {int16_t b,bmin,bmax,bres,bdef;uint16_t c,cmin,cmax,cres,cdef;};
static uvc_error_t read_controls(uvc_device_handle_t *h,struct controls *s){
 uvc_error_t e;
 #define GET_PAIR(req,brightness,contrast) \
  if((e=uvc_get_brightness(h,&s->brightness,req))<0)return e; \
  if((e=uvc_get_contrast(h,&s->contrast,req))<0)return e;
 GET_PAIR(UVC_GET_CUR,b,c)
 GET_PAIR(UVC_GET_MIN,bmin,cmin)
 GET_PAIR(UVC_GET_MAX,bmax,cmax)
 GET_PAIR(UVC_GET_RES,bres,cres)
 GET_PAIR(UVC_GET_DEF,bdef,cdef)
 #undef GET_PAIR
 return UVC_SUCCESS;
}
static void print_controls(FILE *f,const struct controls *s){
 fprintf(f,"{\"brightness_signed\":%d,\"contrast\":%u,\"brightness_min\":%d,\"brightness_max\":%d,\"brightness_resolution\":%d,\"brightness_default\":%d,\"contrast_min\":%u,\"contrast_max\":%u,\"contrast_resolution\":%u,\"contrast_default\":%u}",s->b,s->c,s->bmin,s->bmax,s->bres,s->bdef,s->cmin,s->cmax,s->cres,s->cdef);
}
static void cb(uvc_frame_t *frame,void *user){
 struct capture *c=user;pthread_mutex_lock(&c->lock);
 if(c->failed || c->count>=c->wanted || now()<c->ready){c->skipped++;pthread_mutex_unlock(&c->lock);return;}
 if(frame->width!=1920 || frame->height!=1080 || (strcmp(c->mode,"yuy2")==0 && (frame->frame_format!=UVC_FRAME_FORMAT_YUYV || frame->data_bytes!=1920*1080*2)) || (strcmp(c->mode,"mjpeg")==0 && frame->frame_format!=UVC_FRAME_FORMAT_MJPEG)){
  fprintf(stderr,"Invalid UVC frame: %ux%u fmt=%d bytes=%zu\n",frame->width,frame->height,frame->frame_format,frame->data_bytes);c->failed=1;
 }else{
  char path[4096],name[64];snprintf(name,sizeof(name),"frame-%03u.%s",c->count,strcmp(c->mode,"mjpeg")==0?"jpg":"yuy2");snprintf(path,sizeof(path),"%s/%s",c->out,name);
  FILE *f=fopen(path,"wx");if(!f || fwrite(frame->data,1,frame->data_bytes,f)!=frame->data_bytes)c->failed=1;if(f)fclose(f);
  unsigned char *p=frame->data;int soi=frame->data_bytes>=2 && p[0]==255 && p[1]==216;
  fprintf(c->json,"%s{\"file\":\"%s\",\"width\":%u,\"height\":%u,\"bytes\":%zu,\"sequence\":%u,\"frame_format\":%d,\"pixel_format\":\"%s\",\"pts_seconds\":%.9f,\"jpeg_soi\":%s}",c->count?",\n":"",name,frame->width,frame->height,frame->data_bytes,frame->sequence,frame->frame_format,strcmp(c->mode,"mjpeg")==0?"jpeg":"yuvs",now(),soi?"true":"false");fflush(c->json);
  fprintf(stderr,"Saved raw UVC frame %u/%u: %s %zu bytes\n",++c->count,c->wanted,name,frame->data_bytes);
 }
 pthread_cond_signal(&c->changed);pthread_mutex_unlock(&c->lock);
}
int main(int argc,char **argv){
 if((argc!=3 && argc!=4) || (argc==4 && strcmp(argv[3],"--ui127") && strcmp(argv[3],"--b128-c127")) || (strcmp(argv[1],"yuy2") && strcmp(argv[1],"mjpeg"))){fprintf(stderr,"Usage: capture_video_uvc yuy2|mjpeg NEW_OUTPUT_DIRECTORY [--ui127|--b128-c127]\n");return 2;}
 uvc_context_t *ctx=NULL;uvc_device_t *dev=NULL;uvc_device_handle_t *handle=NULL;uvc_stream_ctrl_t ctrl={0};uvc_error_t e;int rc=1,started=0;
 struct capture c={.out=argv[2],.mode=argv[1],.wanted=8,.lock=PTHREAD_MUTEX_INITIALIZER,.changed=PTHREAD_COND_INITIALIZER};
 struct controls original={0},active={0},restored={0};int test_profile=argc==4,brightness_target=argc==4 && !strcmp(argv[3],"--ui127") ? -1 : 0,changed=0,restoration_ok=1,controls_valid=0;
 if((e=uvc_init(&ctx,NULL))<0)goto error;
 if((e=uvc_find_device(ctx,&dev,0x534d,0x2109,NULL))<0)goto error;
 if((e=uvc_open(dev,&handle))<0)goto error;
 if((e=read_controls(handle,&original))<0)goto error;controls_valid=1;active=original;
 enum uvc_frame_format fmt=strcmp(argv[1],"mjpeg")==0?UVC_FRAME_FORMAT_MJPEG:UVC_FRAME_FORMAT_YUYV;
 if((e=uvc_get_stream_ctrl_format_size(handle,&ctrl,fmt,1920,1080,fmt==UVC_FRAME_FORMAT_MJPEG?30:5))<0)goto error;
 if(mkdir(c.out,0755)<0){perror("New output directory required");goto done;}
 char path[4096];snprintf(path,sizeof(path),"%s/usb-capture.json",c.out);c.json=fopen(path,"wx");if(!c.json){perror("metadata");goto done;}
 snprintf(path,sizeof(path),"%s/controls-before.json",c.out);FILE *journal=fopen(path,"wx");if(!journal)goto done;print_controls(journal,&original);fprintf(journal,"\n");if(fclose(journal))goto done;
 if(test_profile){
  /* The signed UVC brightness domain is distinct from its unsigned UI.
   * Refuse a different device range rather than silently choose a mapping. */
  if(original.bmin!=-128 || original.bmax!=127 || original.bres!=1 || original.cmin!=0 || original.cmax!=255 || original.cres!=1){fprintf(stderr,"Unexpected UVC control range; midpoint mapping not applied\n");goto done;}
  changed=1;
  if((e=uvc_set_brightness(handle,brightness_target))<0)goto error;
  if((e=uvc_set_contrast(handle,127))<0)goto error;
  if((e=read_controls(handle,&active))<0)goto error;
  if(active.b!=brightness_target || active.c!=127){fprintf(stderr,"Test control readback disagrees\n");goto done;}
 }
 fprintf(c.json,"{\"capture_backend\":\"libuvc USB payload, no host pixel conversion\",\"mode\":\"%s\",\"control_profile\":\"%s\",\"controls_before\":",c.mode,test_profile?(brightness_target==-1?"unsigned UI brightness=127 contrast=127":"unsigned UI brightness=128 contrast=127"):"current");print_controls(c.json,&original);fprintf(c.json,",\"controls_active\":");print_controls(c.json,&active);
 fprintf(c.json,",\"vid\":21325,\"pid\":8457,\"format_index\":%u,\"frame_index\":%u,\"interval_100ns\":%u,\"max_frame_bytes\":%u,\"max_payload_bytes\":%u,\"interface\":%u,\"frames\":[\n",ctrl.bFormatIndex,ctrl.bFrameIndex,ctrl.dwFrameInterval,ctrl.dwMaxVideoFrameSize,ctrl.dwMaxPayloadTransferSize,ctrl.bInterfaceNumber);
 c.ready=now()+3;
 if((e=uvc_start_streaming(handle,&ctrl,cb,&c,0))<0)goto error;started=1;
 pthread_mutex_lock(&c.lock);struct timespec deadline;clock_gettime(CLOCK_REALTIME,&deadline);deadline.tv_sec+=20;
 while(!c.failed && c.count<c.wanted){if(pthread_cond_timedwait(&c.changed,&c.lock,&deadline)==ETIMEDOUT){c.failed=1;fprintf(stderr,"20-second UVC acquisition timeout\n");break;}}
 pthread_mutex_unlock(&c.lock);
 rc=(!c.failed && c.count==c.wanted)?0:1;goto done;
error:uvc_perror(e,"UVC acquisition");
done:
 if(started)uvc_stop_streaming(handle);
 if(changed){
  int eb=uvc_set_brightness(handle,original.b),ec=uvc_set_contrast(handle,original.c);
  int er=read_controls(handle,&restored);restoration_ok=eb>=0 && ec>=0 && er>=0 && restored.b==original.b && restored.c==original.c;
  if(!restoration_ok){fprintf(stderr,"ERROR: restoring brightness/contrast failed (b=%d c=%d read=%d)\n",eb,ec,er);rc=1;}
 }else if(controls_valid)restored=original;
 if(c.json){
  /* A setup failure can occur before the frames array is opened. */
  if(ftell(c.json)>0)fprintf(c.json,"\n],\"frames_captured\":%u,\"frames_skipped_for_settling\":%u,\"controls_restored\":",c.count,c.skipped);
  else fprintf(c.json,"{\"frames\":[],\"frames_captured\":0,\"controls_restored\":");
  print_controls(c.json,&restored);fprintf(c.json,",\"controls_restoration_ok\":%s,\"exit_code\":%d}\n",restoration_ok?"true":"false",rc);fclose(c.json);
 }
 if(handle)uvc_close(handle);if(dev)uvc_unref_device(dev);if(ctx)uvc_exit(ctx);return rc;
}
