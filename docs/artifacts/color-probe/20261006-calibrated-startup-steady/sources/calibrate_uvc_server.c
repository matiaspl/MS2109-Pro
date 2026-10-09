/* Bounded, task-specific MS2109 calibration server. Original USB payloads only.
 * Requests: numeric ID, unsigned UI brightness, contrast, saturation; or stop.
 * Controls are restored after EVERY sample, on errors/signals and on timeout.
 * Only the fixed 534d:2109 device is opened. No firmware/EEPROM writes.
 */
#include <libuvc/libuvc.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <time.h>
#include <pthread.h>
#include <signal.h>
#include <sys/stat.h>
#include <errno.h>

static volatile sig_atomic_t interrupted;
static void on_signal(int sig){(void)sig;interrupted=1;}
static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec*1e-9;}
struct controls {int16_t b,h,bmin,bmax,bres;uint16_t c,s,cmin,cmax,cres,smin,smax,sres;};
static int current(uvc_device_handle_t *h,struct controls *s){
 return uvc_get_brightness(h,&s->b,UVC_GET_CUR)<0 || uvc_get_contrast(h,&s->c,UVC_GET_CUR)<0 || uvc_get_saturation(h,&s->s,UVC_GET_CUR)<0 || uvc_get_hue(h,&s->h,UVC_GET_CUR)<0 ? -1:0;
}
static int ranges(uvc_device_handle_t *h,struct controls *s){
 #define GET(field,method,type) if(uvc_get_##method(h,&s->field,type)<0)return -1;
 GET(bmin,brightness,UVC_GET_MIN) GET(bmax,brightness,UVC_GET_MAX) GET(bres,brightness,UVC_GET_RES)
 GET(cmin,contrast,UVC_GET_MIN) GET(cmax,contrast,UVC_GET_MAX) GET(cres,contrast,UVC_GET_RES)
 GET(smin,saturation,UVC_GET_MIN) GET(smax,saturation,UVC_GET_MAX) GET(sres,saturation,UVC_GET_RES)
 #undef GET
 return current(h,s);
}
static void print_controls(FILE *f,const struct controls *s){fprintf(f,"{\"brightness_ui\":%d,\"brightness_signed\":%d,\"contrast\":%u,\"saturation\":%u,\"hue\":%d}",s->b+128,s->b,s->c,s->s,s->h);}
static int restore(uvc_device_handle_t *h,const struct controls *o,struct controls *r){
 int b=uvc_set_brightness(h,o->b),c=uvc_set_contrast(h,o->c),s=uvc_set_saturation(h,o->s);
 return current(h,r)==0 && b>=0 && c>=0 && s>=0 && r->b==o->b && r->c==o->c && r->s==o->s && r->h==o->h;
}
/* Refuse symlinks and overwrites for all files opened by the privileged helper. */
static FILE *new_file(const char *path){int fd=open(path,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0644);return fd<0?NULL:fdopen(fd,"w");}
static int valid_dir(const char *path){struct stat s;return lstat(path,&s)==0 && S_ISDIR(s.st_mode) && !S_ISLNK(s.st_mode);}
static FILE *publish_begin(const char *dir,const char *name,char *tmp,size_t n){snprintf(tmp,n,"%s/.%s.tmp",dir,name);return new_file(tmp);}
static int publish_end(FILE *f,const char *dir,const char *name,const char *tmp){char path[4096];if(fclose(f))return -1;snprintf(path,sizeof(path),"%s/%s",dir,name);if(access(path,F_OK)==0)return -1;return rename(tmp,path);}
struct capture {const char *out,*mode;FILE *json;unsigned count,skipped;int failed;double ready;pthread_mutex_t lock;pthread_cond_t changed;};
static void callback(uvc_frame_t *frame,void *user){
 struct capture *c=user;pthread_mutex_lock(&c->lock);
 if(c->failed || c->count>=3 || now()<c->ready){c->skipped++;pthread_mutex_unlock(&c->lock);return;}
 if(frame->width!=1920 || frame->height!=1080 || (!strcmp(c->mode,"yuy2") && (frame->frame_format!=UVC_FRAME_FORMAT_YUYV || frame->data_bytes!=1920*1080*2)) || (!strcmp(c->mode,"mjpeg") && (frame->frame_format!=UVC_FRAME_FORMAT_MJPEG || frame->data_bytes>16*1024*1024))){c->failed=1;}
 else {
  char path[4096],name[64];snprintf(name,sizeof(name),"frame-%03u.%s",c->count,!strcmp(c->mode,"mjpeg")?"jpg":"yuy2");snprintf(path,sizeof(path),"%s/%s",c->out,name);
  FILE *f=new_file(path);if(!f || fwrite(frame->data,1,frame->data_bytes,f)!=frame->data_bytes)c->failed=1;if(f && fclose(f))c->failed=1;
  fprintf(c->json,"%s{\"file\":\"%s\",\"width\":1920,\"height\":1080,\"bytes\":%zu,\"sequence\":%u,\"pixel_format\":\"%s\"}",c->count?",":"",name,frame->data_bytes,frame->sequence,!strcmp(c->mode,"mjpeg")?"jpeg":"yuvs");fflush(c->json);c->count++;
 }
 pthread_cond_signal(&c->changed);pthread_mutex_unlock(&c->lock);
}
static int capture(uvc_device_handle_t *h,const char *out,const char *mode,const struct controls *active){
 uvc_stream_ctrl_t ctrl={0};enum uvc_frame_format fmt=!strcmp(mode,"mjpeg")?UVC_FRAME_FORMAT_MJPEG:UVC_FRAME_FORMAT_YUYV;
 struct capture c={.out=out,.mode=mode,.lock=PTHREAD_MUTEX_INITIALIZER,.changed=PTHREAD_COND_INITIALIZER};int started=0,ok=0;
 if(mkdir(out,0755)<0)return -1;
 char path[4096];snprintf(path,sizeof(path),"%s/usb-capture.json",out);c.json=new_file(path);if(!c.json)return -1;
 fprintf(c.json,"{\"capture_backend\":\"libuvc original USB payload\",\"mode\":\"%s\",\"controls_active\":",mode);print_controls(c.json,active);fprintf(c.json,",\"frames\":[");
 if(uvc_get_stream_ctrl_format_size(h,&ctrl,fmt,1920,1080,fmt==UVC_FRAME_FORMAT_MJPEG?30:5)<0)goto done;
 c.ready=now()+1.5;
 if(uvc_start_streaming(h,&ctrl,callback,&c,0)<0)goto done;started=1;
 double deadline=now()+20;
 pthread_mutex_lock(&c.lock);
 while(!c.failed && c.count<3 && !interrupted && now()<deadline){struct timespec t;clock_gettime(CLOCK_REALTIME,&t);t.tv_sec++;pthread_cond_timedwait(&c.changed,&c.lock,&t);}
 ok=!c.failed && c.count==3 && !interrupted;pthread_mutex_unlock(&c.lock);
 done:
 if(started)uvc_stop_streaming(h);
 fprintf(c.json,"],\"frames_captured\":%u,\"settling_frames_skipped\":%u,\"exit_code\":%d}\n",c.count,c.skipped,ok?0:1);fclose(c.json);pthread_mutex_destroy(&c.lock);pthread_cond_destroy(&c.changed);return ok?0:-1;
}
int main(int argc,char **argv){
 if(argc!=3 || strcmp(argv[1],"calibrate") || argv[2][0]!='/' || strlen(argv[2])>3000 || !valid_dir(argv[2]))return 2;
 umask(022);signal(SIGINT,on_signal);signal(SIGTERM,on_signal);signal(SIGHUP,on_signal);
 const char *dir=argv[2];uvc_context_t *ctx=NULL;uvc_device_t *dev=NULL;uvc_device_handle_t *h=NULL;struct controls original={0},active={0},restored={0};int valid=0,restored_ok=0,rc=1;unsigned completed=0;char path[4096],tmp[4096];FILE *f=NULL;
 if(uvc_init(&ctx,NULL)<0 || uvc_find_device(ctx,&dev,0x534d,0x2109,NULL)<0 || uvc_open(dev,&h)<0 || ranges(h,&original)<0)goto done;valid=1;
 if(original.bmin!=-128 || original.bmax!=127 || original.bres!=1 || original.cmin!=0 || original.cmax!=255 || original.cres!=1 || original.smin!=0 || original.smax!=255 || original.sres!=1){fprintf(stderr,"Unexpected calibration control ranges\n");goto done;}
 snprintf(path,sizeof(path),"%s/captures",dir);if(mkdir(path,0755)<0)goto done;
 f=publish_begin(dir,"ready.json",tmp,sizeof(tmp));if(!f)goto done;
 fprintf(f,"{\"original\":");print_controls(f,&original);fprintf(f,",\"brightness_ui_range\":[0,255],\"brightness_signed_range\":[-128,127],\"contrast_range\":[0,255],\"saturation_range\":[0,255],\"step\":1,\"frames_per_transport\":3,\"session_timeout_seconds\":900,\"heartbeat_timeout_seconds\":45}\n");if(publish_end(f,dir,"ready.json",tmp)<0)goto done;
 double started=now(),last=started;
 while(!interrupted && completed<80 && now()-started<900 && now()-last<45){
  struct stat hb;snprintf(path,sizeof(path),"%s/heartbeat",dir);if(lstat(path,&hb)==0 && S_ISREG(hb.st_mode) && !S_ISLNK(hb.st_mode) && time(NULL)-hb.st_mtime<10)last=now();
  snprintf(path,sizeof(path),"%s/request.txt",dir);int fd=open(path,O_RDONLY|O_NOFOLLOW);if(fd<0){usleep(100000);continue;}
  struct stat st;if(fstat(fd,&st)<0 || !S_ISREG(st.st_mode) || st.st_size>100){close(fd);goto done;}
  char request[101]={0};ssize_t n=read(fd,request,100);close(fd);if(n<=0)goto done;unlink(path);
  if(!strcmp(request,"stop\n")){rc=0;break;}
  unsigned id;int b,c,s;char trailing;if(sscanf(request,"%u %d %d %d %c",&id,&b,&c,&s,&trailing)!=4 || id!=completed || b<0 || b>255 || c<0 || c>255 || s<0 || s>255)goto done;
  last=now();char base[4096];snprintf(base,sizeof(base),"%s/captures/sample-%03u",dir,id);if(mkdir(base,0755)<0)goto done;
  int ok=uvc_set_brightness(h,b-128)>=0 && uvc_set_contrast(h,c)>=0 && uvc_set_saturation(h,s)>=0 && current(h,&active)==0 && active.b==b-128 && active.c==c && active.s==s && active.h==original.h;
  const char *modes[]={"yuy2","mjpeg"};
  for(unsigned i=0;i<2 && ok && !interrupted;i++){snprintf(path,sizeof(path),"%s/%s",base,modes[i]);ok=capture(h,path,modes[i],&active)==0;}
  restored_ok=restore(h,&original,&restored);if(!restored_ok)ok=0;
  char name[64];snprintf(name,sizeof(name),"response-%03u.json",id);f=publish_begin(dir,name,tmp,sizeof(tmp));if(!f)goto done;
  fprintf(f,"{\"id\":%u,\"controls_active\":",id);print_controls(f,&active);fprintf(f,",\"controls_restored\":");print_controls(f,&restored);fprintf(f,",\"controls_restoration_ok\":%s,\"exit_code\":%d}\n",restored_ok?"true":"false",ok?0:1);if(publish_end(f,dir,name,tmp)<0)goto done;
  fprintf(stdout,"Captured sample %u: UI brightness %d, contrast %d, saturation %d; original controls restored.\n",id,b,c,s);fflush(stdout);completed++;if(!ok)goto done;
 }
 done:
 if(valid){restored_ok=restore(h,&original,&restored);if(!restored_ok)rc=1;}
 if(h)uvc_close(h);if(dev)uvc_unref_device(dev);if(ctx)uvc_exit(ctx);
 f=publish_begin(dir,"session.json",tmp,sizeof(tmp));if(f){fprintf(f,"{\"exit_code\":%d,\"completed_samples\":%u,\"interrupted\":%s,\"controls_original\":",rc,completed,interrupted?"true":"false");print_controls(f,&original);fprintf(f,",\"controls_restored\":");print_controls(f,&restored);fprintf(f,",\"controls_restoration_ok\":%s,\"uvc_handle_closed\":true}\n",restored_ok?"true":"false");publish_end(f,dir,"session.json",tmp);}
 return rc;
}
