/* Capture both native formats sequentially on one open UVC handle.
 * No SET_CUR or firmware/EEPROM writes are issued. */
#include <libuvc/libuvc.h>
#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

struct capture {
    const char *directory;
    const char *mode;
    FILE *metadata;
    FILE *requests;
    unsigned count;
    unsigned skipped;
    int failed;
    double ready;
    pthread_mutex_t mutex;
    pthread_cond_t changed;
};

struct controls { int16_t brightness; uint16_t contrast; };
static volatile sig_atomic_t interrupted;

static void on_signal(int sig) { interrupted = sig; }
static double now(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec * 1e-9;
}

static int read_controls(uvc_device_handle_t *handle, struct capture *c,
                         struct controls *value, const char *phase) {
    uvc_error_t eb = uvc_get_brightness(handle, &value->brightness, UVC_GET_CUR);
    if (c->requests)
        fprintf(c->requests, "{\"phase\":\"%s\",\"selector\":\"BRIGHTNESS\",\"request\":\"GET_CUR\",\"api_status\":%d,\"value\":%d}\n", phase, eb, value->brightness);
    uvc_error_t ec = uvc_get_contrast(handle, &value->contrast, UVC_GET_CUR);
    if (c->requests)
        fprintf(c->requests, "{\"phase\":\"%s\",\"selector\":\"CONTRAST\",\"request\":\"GET_CUR\",\"api_status\":%d,\"value\":%u}\n", phase, ec, value->contrast);
    if (c->requests) fflush(c->requests);
    return eb >= 0 && ec >= 0;
}

static void frame_callback(uvc_frame_t *frame, void *opaque) {
    struct capture *c = opaque;
    pthread_mutex_lock(&c->mutex);
    if (c->failed || c->count >= 8 || now() < c->ready) {
        c->skipped++;
        pthread_mutex_unlock(&c->mutex);
        return;
    }
    int mjpeg = strcmp(c->mode, "mjpeg") == 0;
    if (frame->width != 1920 || frame->height != 1080 ||
        (mjpeg && frame->frame_format != UVC_FRAME_FORMAT_MJPEG) ||
        (!mjpeg && (frame->frame_format != UVC_FRAME_FORMAT_YUYV ||
                    frame->data_bytes != 1920u * 1080u * 2u))) {
        fprintf(stderr, "Unexpected %s frame %ux%u format=%d bytes=%zu\n",
                c->mode, frame->width, frame->height, frame->frame_format, frame->data_bytes);
        c->failed = 1;
    } else {
        char path[4096], name[64];
        snprintf(name, sizeof(name), "frame-%03u.%s", c->count, mjpeg ? "jpg" : "yuy2");
        snprintf(path, sizeof(path), "%s/%s", c->directory, name);
        FILE *file = fopen(path, "wx");
        if (!file || fwrite(frame->data, 1, frame->data_bytes, file) != frame->data_bytes) c->failed = 1;
        if (file) fclose(file);
        unsigned char *bytes = frame->data;
        int soi = frame->data_bytes >= 2 && bytes[0] == 0xff && bytes[1] == 0xd8;
        fprintf(c->metadata,
                "%s{\"file\":\"%s\",\"width\":%u,\"height\":%u,\"bytes\":%zu,\"sequence\":%u,\"pixel_format\":\"%s\",\"pts_seconds\":%.9f,\"jpeg_soi\":%s}",
                c->count ? ",\n" : "", name, frame->width, frame->height, frame->data_bytes,
                frame->sequence, mjpeg ? "jpeg" : "yuvs", now(), soi ? "true" : "false");
        fflush(c->metadata);
        fprintf(stderr, "Same-handle %s frame %u/8 saved (%zu bytes)\n",
                c->mode, c->count + 1, frame->data_bytes);
        c->count++;
    }
    pthread_cond_signal(&c->changed);
    pthread_mutex_unlock(&c->mutex);
}

static int capture_format(uvc_device_handle_t *handle, struct capture *c,
                          struct controls expected, unsigned switch_index) {
    if (mkdir(c->directory, 0755) < 0) { perror("capture directory"); return 1; }
    char path[4096];
    snprintf(path, sizeof(path), "%s/control-requests.jsonl", c->directory);
    c->requests = fopen(path, "wx");
    if (!c->requests) { perror("request log"); return 1; }
    struct controls before = {0}, after = {0};
    if (!read_controls(handle, c, &before, "before-format")) return 1;
    if (before.brightness != expected.brightness || before.contrast != expected.contrast) {
        fprintf(stderr, "Picture controls changed before same-handle format %s\n", c->mode);
        return 1;
    }
    enum uvc_frame_format format = strcmp(c->mode, "mjpeg") == 0 ?
        UVC_FRAME_FORMAT_MJPEG : UVC_FRAME_FORMAT_YUYV;
    uvc_stream_ctrl_t control = {0};
    uvc_error_t error = uvc_get_stream_ctrl_format_size(handle, &control, format,
        1920, 1080, format == UVC_FRAME_FORMAT_MJPEG ? 30 : 5);
    if (error < 0) { uvc_perror(error, "negotiate same-handle stream"); return 1; }

    snprintf(path, sizeof(path), "%s/usb-capture.json", c->directory);
    c->metadata = fopen(path, "wx");
    if (!c->metadata) { perror("capture metadata"); return 1; }
    fprintf(c->metadata,
        "{\"capture_backend\":\"libuvc raw payload, persistent handle\",\"handle_session_pid\":%d,\"switch_index\":%u,\"mode\":\"%s\",\"getter_profile\":\"GET_CUR only\",\"control_profile\":\"untouched\",\"controls_before\":{\"brightness_signed\":%d,\"contrast\":%u},\"controls_active\":{\"brightness_signed\":%d,\"contrast\":%u},\"vid\":21325,\"pid\":8457,\"format_index\":%u,\"frame_index\":%u,\"interval_100ns\":%u,\"max_frame_bytes\":%u,\"max_payload_bytes\":%u,\"interface\":%u,\"frames\":[\n",
        getpid(), switch_index, c->mode, before.brightness, before.contrast,
        before.brightness, before.contrast, control.bFormatIndex, control.bFrameIndex,
        control.dwFrameInterval, control.dwMaxVideoFrameSize, control.dwMaxPayloadTransferSize,
        control.bInterfaceNumber);
    fflush(c->metadata);
    c->count = c->skipped = 0;
    c->failed = 0;
    c->ready = now() + 3.0;
    error = uvc_start_streaming(handle, &control, frame_callback, c, 0);
    if (error < 0) {
        uvc_perror(error, "start same-handle stream");
        fclose(c->metadata); c->metadata = NULL;
        fclose(c->requests); c->requests = NULL;
        return 1;
    }
    pthread_mutex_lock(&c->mutex);
    double deadline = now() + 20.0;
    while (!c->failed && c->count < 8 && !interrupted) {
        struct timespec wake;
        clock_gettime(CLOCK_REALTIME, &wake);
        wake.tv_nsec += 200000000;
        if (wake.tv_nsec >= 1000000000) { wake.tv_sec++; wake.tv_nsec -= 1000000000; }
        if (pthread_cond_timedwait(&c->changed, &c->mutex, &wake) == ETIMEDOUT && now() >= deadline) {
            c->failed = 1;
            fprintf(stderr, "20-second same-handle acquisition timeout\n");
            break;
        }
    }
    pthread_mutex_unlock(&c->mutex);
    uvc_stop_streaming(handle);
    int status = !c->failed && c->count == 8 && !interrupted;
    if (status && !read_controls(handle, c, &after, "after-format-stop")) status = 0;
    int controls_match = status && after.brightness == expected.brightness &&
                        after.contrast == expected.contrast;
    if (!controls_match) status = 0;
    fprintf(c->metadata,
        "\n],\"frames_captured\":%u,\"frames_skipped_for_settling\":%u,\"controls_after\":{\"brightness_signed\":%d,\"contrast\":%u},\"controls_restoration_ok\":%s,\"exit_code\":%d}\n",
        c->count, c->skipped, after.brightness, after.contrast,
        controls_match ? "true" : "false", status ? 0 : 1);
    fclose(c->metadata); c->metadata = NULL;
    fclose(c->requests); c->requests = NULL;
    return status ? 0 : 1;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "Usage: capture_uvc_same_handle NEW_OUTPUT_DIRECTORY\n");
        return 2;
    }
    signal(SIGINT, on_signal); signal(SIGTERM, on_signal);
    if (mkdir(argv[1], 0755) < 0 && errno != EEXIST) { perror("new output directory required"); return 2; }
    uvc_context_t *context = NULL;
    uvc_device_t *device = NULL;
    uvc_device_handle_t *handle = NULL;
    uvc_error_t error = uvc_init(&context, NULL);
    if (error < 0) { uvc_perror(error, "uvc_init"); return 1; }
    error = uvc_find_device(context, &device, 0x534d, 0x2109, NULL);
    if (error < 0) { uvc_perror(error, "find MS2109"); uvc_exit(context); return 1; }
    error = uvc_open(device, &handle);
    if (error < 0) { uvc_perror(error, "open MS2109"); uvc_unref_device(device); uvc_exit(context); return 1; }

    struct capture c = {.mutex = PTHREAD_MUTEX_INITIALIZER,
                        .changed = PTHREAD_COND_INITIALIZER};
    struct controls initial = {0};
    c.directory = argv[1];
    c.mode = "mjpeg";
    char request_path[4096];
    snprintf(request_path, sizeof(request_path), "%s/initial-controls.jsonl", c.directory);
    c.requests = fopen(request_path, "wx");
    if (!c.requests || !read_controls(handle, &c, &initial, "before-first-format")) {
        fprintf(stderr, "Could not read initial controls\n"); goto fail;
    }
    fclose(c.requests); c.requests = NULL;
    char path[4096];
    snprintf(path, sizeof(path), "%s/mjpeg", argv[1]); c.directory = path;
    if (capture_format(handle, &c, initial, 0)) goto fail;
    snprintf(path, sizeof(path), "%s/yuy2", argv[1]); c.directory = path; c.mode = "yuy2";
    if (capture_format(handle, &c, initial, 1)) goto fail;
    uvc_close(handle); uvc_unref_device(device); uvc_exit(context);
    fprintf(stderr, "Same-handle MJPEG then YUY2 sequence completed without SET_CUR.\n");
    return 0;
fail:
    if (c.metadata) fclose(c.metadata);
    if (c.requests) fclose(c.requests);
    if (handle) uvc_close(handle);
    if (device) uvc_unref_device(device);
    if (context) uvc_exit(context);
    return 1;
}
