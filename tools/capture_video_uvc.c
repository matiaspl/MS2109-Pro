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
#include <signal.h>
#include <sys/stat.h>
#include <errno.h>

struct capture {const char *out,*mode; FILE *json; unsigned count,wanted,skipped;int failed;double ready;pthread_mutex_t lock;pthread_cond_t changed;};
static volatile sig_atomic_t interrupted=0;
static void on_signal(int sig){interrupted=sig;}
static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec*1e-9;}
struct controls {int16_t b,bmin,bmax,bres,bdef;uint16_t c,cmin,cmax,cres,cdef;};
static FILE *request_log;
static const char *request_phase="unspecified";
static int get_one(uvc_device_handle_t *h, int req, const char *selector,
                   int brightness, void *value){
 uvc_error_t e=brightness?uvc_get_brightness(h,(int16_t*)value,req):uvc_get_contrast(h,(uint16_t*)value,req);
 if(request_log){
  long numeric=brightness?*(int16_t*)value:*(uint16_t*)value;
  fprintf(request_log,"{\"phase\":\"%s\",\"direction\":\"IN\",\"bmRequestType\":161,\"bRequest\":%d,\"wValue\":%d,\"entity_id\":\"resolved-by-libuvc\",\"selector\":\"%s\",\"api_status\":%d,\"value\":%ld}\n",
   request_phase,req,brightness?0x0200:0x0300,selector,e,(e<0)?0:numeric);fflush(request_log);
 }
 return e;
}
static int set_one(uvc_device_handle_t *h, const char *selector, int brightness, int value){
 uvc_error_t e=brightness?uvc_set_brightness(h,(int16_t)value):uvc_set_contrast(h,(uint16_t)value);
 if(request_log)fprintf(request_log,"{\"phase\":\"%s\",\"direction\":\"OUT\",\"bmRequestType\":33,\"bRequest\":1,\"wValue\":%d,\"entity_id\":\"resolved-by-libuvc\",\"selector\":\"%s\",\"api_status\":%d,\"value\":%d}\n",request_phase,brightness?0x0200:0x0300,selector,e,value);
 return e;
}
static uvc_error_t read_controls(uvc_device_handle_t *h,struct controls *s,int all){
 uvc_error_t e;
 request_phase="GET_CUR";
 if((e=get_one(h,UVC_GET_CUR,"BRIGHTNESS",1,&s->b))<0)return e;
 if((e=get_one(h,UVC_GET_CUR,"CONTRAST",0,&s->c))<0)return e;
 if(!all)return UVC_SUCCESS;
 const int reqs[]={UVC_GET_MIN,UVC_GET_MAX,UVC_GET_RES,UVC_GET_DEF};
 const char *names[]={"GET_MIN","GET_MAX","GET_RES","GET_DEF"};
 int16_t *bv[]={&s->bmin,&s->bmax,&s->bres,&s->bdef};
 uint16_t *cv[]={&s->cmin,&s->cmax,&s->cres,&s->cdef};
 for(unsigned i=0;i<4;i++){
  request_phase=names[i];
  if((e=get_one(h,reqs[i],"BRIGHTNESS",1,bv[i]))<0)return e;
  if((e=get_one(h,reqs[i],"CONTRAST",0,cv[i]))<0)return e;
 }
 return UVC_SUCCESS;
}
static void print_controls(FILE *f,const struct controls *s,int all){
 if(all)fprintf(f,"{\"brightness_signed\":%d,\"contrast\":%u,\"brightness_min\":%d,\"brightness_max\":%d,\"brightness_resolution\":%d,\"brightness_default\":%d,\"contrast_min\":%u,\"contrast_max\":%u,\"contrast_resolution\":%u,\"contrast_default\":%u}",s->b,s->c,s->bmin,s->bmax,s->bres,s->bdef,s->cmin,s->cmax,s->cres,s->cdef);
 else fprintf(f,"{\"brightness_signed\":%d,\"contrast\":%u,\"other_getters\":null}",s->b,s->c);
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
 signal(SIGINT,on_signal);signal(SIGTERM,on_signal);
 if(argc<3 || (strcmp(argv[1],"yuy2") && strcmp(argv[1],"mjpeg"))){fprintf(stderr,"Usage: capture_video_uvc yuy2|mjpeg NEW_OUTPUT_DIRECTORY [--ui127|--b128-c127] [--get-cur-only] [--reapply-current] [--first-frames]\n");return 2;}
 uvc_context_t *ctx=NULL;uvc_device_t *dev=NULL;uvc_device_handle_t *handle=NULL;uvc_stream_ctrl_t ctrl={0};uvc_error_t e;int rc=1,started=0;
 struct capture c={.out=argv[2],.mode=argv[1],.wanted=8,.lock=PTHREAD_MUTEX_INITIALIZER,.changed=PTHREAD_COND_INITIALIZER};
 struct controls original={0},active={0},restored={0};int test_profile=0,brightness_target=0,changed=0,restoration_ok=1,controls_valid=0,cur_only=0,reapply=0,claim_only=0,all_getters=1,first_frames=0;
 for(int i=3;i<argc;i++){
  if(!strcmp(argv[i],"--ui127")){test_profile=1;brightness_target=-1;}
  else if(!strcmp(argv[i],"--b128-c127")){test_profile=1;brightness_target=0;}
  else if(!strcmp(argv[i],"--get-cur-only"))cur_only=1;
  else if(!strcmp(argv[i],"--reapply-current"))reapply=1;
  else if(!strcmp(argv[i],"--first-frames"))first_frames=1;
  else if(!strcmp(argv[i],"--claim-only"))claim_only=1;
  else{fprintf(stderr,"Unknown option: %s\n",argv[i]);return 2;}
 }
 if(test_profile && cur_only){fprintf(stderr,"Explicit test controls require all getter readbacks\n");return 2;}
 all_getters=!cur_only;
 if(mkdir(c.out,0755)<0){perror("New output directory required");goto done;}
 char path[4096];snprintf(path,sizeof(path),"%s/control-requests.jsonl",c.out);request_log=fopen(path,"wx");if(!request_log){perror("request log");goto done;}
 if((e=uvc_init(&ctx,NULL))<0)goto error;
 if((e=uvc_find_device(ctx,&dev,0x534d,0x2109,NULL))<0)goto error;
 if((e=uvc_open(dev,&handle))<0)goto error;
 if((e=read_controls(handle,&original,all_getters))<0)goto error;controls_valid=1;active=original;
 if(claim_only){
  snprintf(path,sizeof(path),"%s/usb-capture.json",c.out);c.json=fopen(path,"wx");if(!c.json){perror("metadata");goto done;}
  fprintf(c.json,"{\"capture_backend\":\"libuvc USB claim only\",\"mode\":\"%s\",\"getter_profile\":\"%s\",\"controls_before\":",c.mode,all_getters?"GET_CUR/MIN/MAX/RES/DEF":"GET_CUR only");print_controls(c.json,&original,all_getters);
  fprintf(c.json,",\"controls_restored\":");print_controls(c.json,&original,all_getters);fprintf(c.json,",\"controls_restoration_ok\":true,\"frames\":[],\"exit_code\":0}\n");fclose(c.json);c.json=NULL;restored=original;controls_valid=0;rc=0;goto done;
 }
 enum uvc_frame_format fmt=strcmp(argv[1],"mjpeg")==0?UVC_FRAME_FORMAT_MJPEG:UVC_FRAME_FORMAT_YUYV;
 if((e=uvc_get_stream_ctrl_format_size(handle,&ctrl,fmt,1920,1080,fmt==UVC_FRAME_FORMAT_MJPEG?30:5))<0)goto error;
 snprintf(path,sizeof(path),"%s/usb-capture.json",c.out);c.json=fopen(path,"wx");if(!c.json){perror("metadata");goto done;}
 snprintf(path,sizeof(path),"%s/controls-before.json",c.out);FILE *journal=fopen(path,"wx");if(!journal)goto done;print_controls(journal,&original,all_getters);fprintf(journal,"\n");if(fclose(journal))goto done;
 if(test_profile){
  /* The signed UVC brightness domain is distinct from its unsigned UI.
   * Refuse a different device range rather than silently choose a mapping. */
  if(original.bmin!=-128 || original.bmax!=127 || original.bres!=1 || original.cmin!=0 || original.cmax!=255 || original.cres!=1){fprintf(stderr,"Unexpected UVC control range; midpoint mapping not applied\n");goto done;}
  changed=1;request_phase="SET_CUR test profile";
  if((e=set_one(handle,"BRIGHTNESS",1,brightness_target))<0)goto error;
  if((e=set_one(handle,"CONTRAST",0,127))<0)goto error;
  if((e=read_controls(handle,&active,all_getters))<0)goto error;
  if(active.b!=brightness_target || active.c!=127){fprintf(stderr,"Test control readback disagrees\n");goto done;}
 }
 if(reapply && !test_profile){changed=1;request_phase="SET_CUR reapply-current";if((e=set_one(handle,"BRIGHTNESS",1,original.b))<0)goto error;if((e=set_one(handle,"CONTRAST",0,original.c))<0)goto error;if((e=read_controls(handle,&active,1))<0)goto error;if(active.b!=original.b || active.c!=original.c){fprintf(stderr,"Reapplied SET_CUR values did not read back unchanged\n");goto done;}}
 fprintf(c.json,"{\"capture_backend\":\"libuvc USB payload, no host pixel conversion\",\"mode\":\"%s\",\"getter_profile\":\"%s\",\"control_profile\":\"%s\",\"controls_before\":",c.mode,all_getters?"GET_CUR/MIN/MAX/RES/DEF":"GET_CUR only",test_profile?(brightness_target==-1?"unsigned UI brightness=127 contrast=127":"unsigned UI brightness=128 contrast=127"):reapply?"reapplied current values":"untouched");print_controls(c.json,&original,all_getters);fprintf(c.json,",\"controls_active\":");print_controls(c.json,&active,all_getters);
 fprintf(c.json,",\"vid\":21325,\"pid\":8457,\"format_index\":%u,\"frame_index\":%u,\"interval_100ns\":%u,\"max_frame_bytes\":%u,\"max_payload_bytes\":%u,\"interface\":%u,\"frames\":[\n",ctrl.bFormatIndex,ctrl.bFrameIndex,ctrl.dwFrameInterval,ctrl.dwMaxVideoFrameSize,ctrl.dwMaxPayloadTransferSize,ctrl.bInterfaceNumber);
 c.ready=now()+(first_frames?0:3);
 if((e=uvc_start_streaming(handle,&ctrl,cb,&c,0))<0)goto error;started=1;
 pthread_mutex_lock(&c.lock);double deadline_mono=now()+20;
 while(!c.failed && c.count<c.wanted && !interrupted){
  struct timespec wake;clock_gettime(CLOCK_REALTIME,&wake);wake.tv_nsec+=200000000;
  if(wake.tv_nsec>=1000000000){wake.tv_sec++;wake.tv_nsec-=1000000000;}
  if(pthread_cond_timedwait(&c.changed,&c.lock,&wake)==ETIMEDOUT && now()>=deadline_mono){c.failed=1;fprintf(stderr,"20-second UVC acquisition timeout\n");break;}
 }
 pthread_mutex_unlock(&c.lock);
 rc=interrupted?128+interrupted:(!c.failed && c.count==c.wanted)?0:1;
 if(interrupted)fprintf(stderr,"Signal %d received; stopping stream and restoring controls before releasing UVC.\n",(int)interrupted);
 goto done;
error:uvc_perror(e,"UVC acquisition");
done:
 if(started)uvc_stop_streaming(handle);
 if(changed){
  request_phase="SET_CUR restore";int eb=set_one(handle,"BRIGHTNESS",1,original.b),ec=set_one(handle,"CONTRAST",0,original.c);
  request_phase="GET_CUR restore readback";int er=read_controls(handle,&restored,all_getters);restoration_ok=eb>=0 && ec>=0 && er>=0 && restored.b==original.b && restored.c==original.c;
  if(!restoration_ok){fprintf(stderr,"ERROR: restoring brightness/contrast failed (b=%d c=%d read=%d)\n",eb,ec,er);rc=1;}
 }else if(controls_valid)restored=original;
 if(c.json){
  /* A setup failure can occur before the frames array is opened. */
  if(ftell(c.json)>0)fprintf(c.json,"\n],\"frames_captured\":%u,\"frames_skipped_for_settling\":%u,\"controls_restored\":",c.count,c.skipped);
  else fprintf(c.json,"{\"frames\":[],\"frames_captured\":0,\"controls_restored\":");
  print_controls(c.json,&restored,all_getters);fprintf(c.json,",\"controls_restoration_ok\":%s,\"exit_code\":%d}\n",restoration_ok?"true":"false",rc);fclose(c.json);
 }
 if(request_log)fclose(request_log);
 if(handle)uvc_close(handle);if(dev)uvc_unref_device(dev);if(ctx)uvc_exit(ctx);return rc;
}
