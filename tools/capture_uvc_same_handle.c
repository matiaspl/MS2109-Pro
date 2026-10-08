/* Capture both native formats sequentially on one open UVC handle.
 * Optional --live-hook mode reads and changes only volatile XDATA through
 * HIDAPI in this same process while UVC streaming is active. */
#include <libuvc/libuvc.h>
#include <hidapi/hidapi.h>
#include <libusb-1.0/libusb.h>
#include <CommonCrypto/CommonDigest.h>
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
    int live_hook;
    int live_state;
    hid_device *hid;
    struct libusb_device_handle *usb_handle;
    FILE *register_log;
    uint16_t target;
    int hid_interface;
    uint8_t mask;
    uint8_t requested_fe8e;
    uint8_t requested_fe8f;
    uint8_t original_fe8e;
    uint8_t original_fe8f;
    int original_valid;
    size_t eeprom_size;
    char eeprom_sha256[65];
    double ready;
    pthread_mutex_t mutex;
    pthread_cond_t changed;
};

struct controls { int16_t brightness; uint16_t contrast; };
static volatile sig_atomic_t interrupted;
static const char *expected_eeprom_sha256 =
    "2c8e7378b6d23c324726b0fc641f9170af92692b00cf272fe59fda43c9f2fdc5";

static void on_signal(int sig) { interrupted = sig; }
static double now(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec * 1e-9;
}

static int feature_read(struct capture *c, uint8_t command, uint16_t address,
                        uint8_t *value) {
    unsigned char report[9] = {0, command, (unsigned char)(address >> 8),
                               (unsigned char)address, 0, 0, 0, 0,
                               (uint8_t)(command == 0xe5 && c->eeprom_size > 2048)};
    if (c->usb_handle) {
        int sent = libusb_control_transfer(c->usb_handle, 0x21, 0x09, 0x0300,
            (uint16_t)c->hid_interface, report + 1, sizeof(report) - 1, 1000);
        if (sent != (int)sizeof(report) - 1) {
            fprintf(stderr, "USB feature SET_REPORT %02X failed at %04X: %s (%d).\n",
                    command, address, libusb_error_name(sent), sent);
            return 0;
        }
        int received = libusb_control_transfer(c->usb_handle, 0xa1, 0x01, 0x0300,
            (uint16_t)c->hid_interface, report + 1, sizeof(report) - 1, 1000);
        if (received != (int)sizeof(report) - 1) {
            fprintf(stderr, "USB feature GET_REPORT %02X failed at %04X: %s (%d).\n",
                    command, address, libusb_error_name(received), received);
            return 0;
        }
        report[0] = 0;
    } else {
        if (!c->hid || hid_send_feature_report(c->hid, report, sizeof(report)) != (int)sizeof(report)) {
            if (c->hid) fwprintf(stderr, L"HID read command %02X failed at %04X: %ls\n", command, address, hid_error(c->hid));
            else fprintf(stderr, "No HID or USB handle available for XDATA read at %04X.\n", address);
            return 0;
        }
        report[0] = 0;
        if (hid_get_feature_report(c->hid, report, sizeof(report)) != (int)sizeof(report)) {
            fwprintf(stderr, L"HID read response %02X failed at %04X: %ls\n", command, address, hid_error(c->hid));
            return 0;
        }
    }
    if (report[1] != command || report[2] != (unsigned char)(address >> 8) ||
        report[3] != (unsigned char)address) {
        fprintf(stderr, "Invalid HID read response %02X at %04X.\n", command, address);
        return 0;
    }
    *value = report[4];
    return 1;
}

static int xdata_read(struct capture *c, uint16_t address, uint8_t *value) {
    return feature_read(c, 0xb5, address, value);
}

static void format_sha256(const uint8_t digest[CC_SHA256_DIGEST_LENGTH], char hex[65]) {
    for (unsigned i = 0; i < CC_SHA256_DIGEST_LENGTH; i++)
        snprintf(hex + i * 2, 3, "%02x", digest[i]);
    hex[64] = '\0';
}

static int read_stable_eeprom(struct capture *c, char hash[65]) {
    uint8_t magic[2] = {0};
    if (!xdata_read(c, 0xcbd0, &magic[0]) || !xdata_read(c, 0xcbd1, &magic[1])) return 0;
    if (magic[0] == 0xa5 && magic[1] == 0x5a) c->eeprom_size = 2048;
    else if (magic[0] == 0x96 && magic[1] == 0x69) c->eeprom_size = 4096;
    else {
        fprintf(stderr, "Unknown EEPROM signature in RAM: %02X%02X.\n", magic[0], magic[1]);
        return 0;
    }
    uint8_t signature[2] = {0};
    if (!feature_read(c, 0xe5, 0, &signature[0]) ||
        !feature_read(c, 0xe5, 1, &signature[1]) ||
        signature[0] != magic[0] || signature[1] != magic[1]) {
        fprintf(stderr, "EEPROM signature does not match the active firmware signature.\n");
        return 0;
    }
    uint8_t *first = malloc(c->eeprom_size), *second = malloc(c->eeprom_size);
    if (!first || !second) { free(first); free(second); return 0; }
    for (size_t i = 0; i < c->eeprom_size; i++) {
        if (!feature_read(c, 0xe5, (uint16_t)i, &first[i])) {
            free(first); free(second); return 0;
        }
    }
    for (size_t i = 0; i < c->eeprom_size; i++) {
        if (!feature_read(c, 0xe5, (uint16_t)i, &second[i])) {
            free(first); free(second); return 0;
        }
    }
    if (memcmp(first, second, c->eeprom_size) != 0) {
        fprintf(stderr, "Two complete EEPROM reads disagree.\n");
        free(first); free(second); return 0;
    }
    uint8_t digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(first, (CC_LONG)c->eeprom_size, digest);
    format_sha256(digest, hash);
    free(first); free(second);
    return 1;
}

static int xdata_write(struct capture *c, uint16_t address, uint8_t value) {
    unsigned char report[9] = {0, 0xb6, (unsigned char)(address >> 8),
                               (unsigned char)address, value, 0, 0, 0, 0};
    if (c->usb_handle) {
        int sent = libusb_control_transfer(c->usb_handle, 0x21, 0x09, 0x0300,
            (uint16_t)c->hid_interface, report + 1, sizeof(report) - 1, 1000);
        if (sent != (int)sizeof(report) - 1) {
            fprintf(stderr, "USB feature SET_REPORT RAM write failed at %04X: %s (%d).\n",
                    address, libusb_error_name(sent), sent);
            return 0;
        }
    } else if (!c->hid || hid_send_feature_report(c->hid, report, sizeof(report)) != (int)sizeof(report)) {
        if (c->hid) fwprintf(stderr, L"HID RAM write command failed at %04X: %ls\n", address, hid_error(c->hid));
        else fprintf(stderr, "No HID or USB handle available for XDATA write at %04X.\n", address);
        return 0;
    }
    uint8_t actual = 0;
    if (!xdata_read(c, address, &actual) || actual != value) {
        fprintf(stderr, "RAM write readback mismatch at %04X: wrote %02X, read %02X.\n",
                address, value, actual);
        return 0;
    }
    return 1;
}

static int read_register_block(struct capture *c, uint8_t block[16]) {
    for (unsigned i = 0; i < 16; i++)
        if (!xdata_read(c, (uint16_t)(0xfe80 + i), &block[i])) return 0;
    return 1;
}

static int reopen_hid(struct capture *c) {
    if (c->hid) hid_close(c->hid);
    c->usb_handle = NULL;
    c->hid = hid_open(0x534d, 0x2109, NULL);
    if (!c->hid) {
        fwprintf(stderr, L"Could not reopen MS2109 HID interface: %ls\n",
                 hid_error(NULL));
        return 0;
    }
    uint8_t id[3] = {0};
    for (unsigned i = 0; i < 3; i++)
        if (!xdata_read(c, (uint16_t)(0xf800 + i), &id[i])) return 0;
    if (id[0] != 0xa7 || id[1] != 0x10 || id[2] != 0x9a) {
        fprintf(stderr, "Unexpected silicon ID after HID reopen: %02X%02X%02X.\n",
                id[0], id[1], id[2]);
        return 0;
    }
    fprintf(stderr, "Reopened and re-identified the MS2109 HID interface.\n");
    return 1;
}

static void log_register_event(struct capture *c, const char *kind, unsigned sequence,
                               const uint8_t *before, const uint8_t *after,
                               uint8_t target_value) {
    if (!c->register_log) return;
    fprintf(c->register_log,
            "{\"kind\":\"%s\",\"sequence\":%u,\"mode\":\"%s\","
            "\"monotonic\":%.9f,\"target_address\":\"%04X\",\"toggle_mask\":\"%02X\","
            "\"target_value\":%u,\"register_block_before\":\"",
            kind, sequence, c->mode, now(), c->target, c->mask, target_value);
    if (before) for (unsigned i = 0; i < 16; i++) fprintf(c->register_log, "%s%02X", i ? " " : "", before[i]);
    fprintf(c->register_log, "\",\"register_block_after\":\"");
    if (after) for (unsigned i = 0; i < 16; i++) fprintf(c->register_log, "%s%02X", i ? " " : "", after[i]);
    fprintf(c->register_log, "\"}\n");
    fflush(c->register_log);
}

static void log_register_sample(struct capture *c, unsigned sequence) {
    if (!c->register_log || (!c->hid && !c->usb_handle) || !c->target) return;
    uint8_t value = 0, fe8e = 0, fe8f = 0;
    if (!xdata_read(c, 0xfe8e, &fe8e) || !xdata_read(c, 0xfe8f, &fe8f)) {
        c->failed = 1;
        return;
    }
    value = c->target == 0xfe8e ? fe8e : fe8f;
    fprintf(c->register_log,
            "{\"kind\":\"sample\",\"sequence\":%u,\"mode\":\"%s\","
            "\"monotonic\":%.9f,\"target_address\":\"%04X\",\"target_value\":%u,"
            "\"fe8e_value\":%u,\"fe8f_value\":%u}\n",
            sequence, c->mode, now(), c->target, value, fe8e, fe8f);
    fflush(c->register_log);
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
        "{\"capture_backend\":\"libuvc raw payload, persistent handle\",\"handle_session_pid\":%d,\"switch_index\":%u,\"mode\":\"%s\",\"getter_profile\":\"GET_CUR only\",\"control_profile\":\"untouched\",\"live_ram_hook\":%s,\"controls_before\":{\"brightness_signed\":%d,\"contrast\":%u},\"controls_active\":{\"brightness_signed\":%d,\"contrast\":%u},\"vid\":21325,\"pid\":8457,\"format_index\":%u,\"frame_index\":%u,\"interval_100ns\":%u,\"max_frame_bytes\":%u,\"max_payload_bytes\":%u,\"interface\":%u,\"frames\":[\n",
        getpid(), switch_index, c->mode, c->live_hook ? "true" : "false", before.brightness, before.contrast,
        before.brightness, before.contrast, control.bFormatIndex, control.bFrameIndex,
        control.dwFrameInterval, control.dwMaxVideoFrameSize, control.dwMaxPayloadTransferSize,
        control.bInterfaceNumber);
    fflush(c->metadata);
    c->count = c->skipped = 0;
    c->failed = 0;
    c->ready = now() + (c->live_hook ? 3600.0 : 3.0);
    error = uvc_start_streaming(handle, &control, frame_callback, c, 0);
    if (error < 0) {
        uvc_perror(error, "start same-handle stream");
        fclose(c->metadata); c->metadata = NULL;
        fclose(c->requests); c->requests = NULL;
        return 1;
    }
    uint8_t mode_before[16] = {0}, mode_after[16] = {0};
    uint8_t mode_target = 0;
    int mode_target_valid = 0;
    if (c->live_hook) {
        c->usb_handle = uvc_get_libusb_handle(handle);
        if (!c->usb_handle) {
            fprintf(stderr, "libuvc did not expose its active USB handle.\n");
            c->failed = 1;
        } else if (!read_register_block(c, mode_before)) {
            fprintf(stderr, "Could not read FE80-FE8F while %s is streaming.\n", c->mode);
            c->failed = 1;
        } else {
            mode_target = mode_before[c->target - 0xfe80];
            mode_target_valid = 1;
            if (c->live_state) {
                if ((mode_before[0x0e] != c->requested_fe8e &&
                     !xdata_write(c, 0xfe8e, c->requested_fe8e)) ||
                    (mode_before[0x0f] != c->requested_fe8f &&
                     !xdata_write(c, 0xfe8f, c->requested_fe8f)))
                    c->failed = 1;
            } else if (c->mask &&
                       !xdata_write(c, c->target, (uint8_t)(mode_target ^ c->mask))) {
                c->failed = 1;
            }
            if (!read_register_block(c, mode_after)) c->failed = 1;
            log_register_event(c, "stream-start", switch_index, mode_before, mode_after,
                               mode_after[c->target - 0xfe80]);
            if (!c->failed) {
                if (c->live_state &&
                    (mode_after[0x0e] != c->requested_fe8e ||
                     mode_after[0x0f] != c->requested_fe8f)) {
                    fprintf(stderr, "FE8E/FE8F did not retain requested state during %s.\n", c->mode);
                    c->failed = 1;
                } else if (!c->live_state && c->mask &&
                           mode_after[c->target - 0xfe80] != (uint8_t)(mode_target ^ c->mask)) {
                    fprintf(stderr, "Live register bit did not retain requested value during %s.\n", c->mode);
                    c->failed = 1;
                }
            }
        }
    }
    c->ready = now() + 3.0;
    pthread_mutex_lock(&c->mutex);
    double deadline = now() + 20.0;
    while (!c->failed && c->count < 8 && !interrupted) {
        struct timespec wake;
        clock_gettime(CLOCK_REALTIME, &wake);
        wake.tv_nsec += 200000000;
        if (wake.tv_nsec >= 1000000000) { wake.tv_sec++; wake.tv_nsec -= 1000000000; }
        pthread_cond_timedwait(&c->changed, &c->mutex, &wake);
        pthread_mutex_unlock(&c->mutex);
        if (c->live_hook) log_register_sample(c, switch_index);
        pthread_mutex_lock(&c->mutex);
        if (now() >= deadline && !c->failed && c->count < 8) {
            c->failed = 1;
            fprintf(stderr, "20-second same-handle acquisition timeout\n");
            break;
        }
    }
    pthread_mutex_unlock(&c->mutex);
    uvc_stop_streaming(handle);
    if (c->live_hook) {
        if (c->live_state && mode_target_valid) {
            if (!xdata_write(c, 0xfe8e, mode_before[0x0e]) ||
                !xdata_write(c, 0xfe8f, mode_before[0x0f])) c->failed = 1;
        } else if (c->mask && mode_target_valid &&
                   !xdata_write(c, c->target, mode_target)) c->failed = 1;
        if (!read_register_block(c, mode_after)) c->failed = 1;
        log_register_event(c, "stream-stop-restore", switch_index, mode_before, mode_after,
                           mode_after[c->target - 0xfe80]);
        if (c->live_state && mode_target_valid &&
            (mode_after[0x0e] != mode_before[0x0e] || mode_after[0x0f] != mode_before[0x0f])) {
            fprintf(stderr, "FE8E/FE8F mode baseline restore failed after %s.\n", c->mode);
            c->failed = 1;
        } else if (c->mask && mode_target_valid &&
                   mode_after[c->target - 0xfe80] != mode_target) {
            fprintf(stderr, "Mode baseline restore failed at %04X after %s.\n", c->target, c->mode);
            c->failed = 1;
        }
    }
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
    if (argc != 2 && argc != 5) {
        fprintf(stderr, "Usage: capture_uvc_same_handle NEW_OUTPUT_DIRECTORY [--live-hook TARGET MASK | --live-state FE8E FE8F]\n");
        return 2;
    }
    int live_hook = argc == 5 && strcmp(argv[2], "--live-hook") == 0;
    int live_state = argc == 5 && strcmp(argv[2], "--live-state") == 0;
    if (argc == 5 && !live_hook && !live_state) return 2;
    unsigned long parsed_target = 0, parsed_mask = 0;
    unsigned long parsed_fe8e = 0, parsed_fe8f = 0;
    if (live_hook) {
        char *end = NULL;
        parsed_target = strtoul(argv[3], &end, 16);
        if (!end || *end) return 2;
        parsed_mask = strtoul(argv[4], &end, 16);
        if (!end || *end || parsed_mask > 0xff ||
            (parsed_target != 0xfe8e && parsed_target != 0xfe8f)) return 2;
    } else if (live_state) {
        char *end = NULL;
        parsed_fe8e = strtoul(argv[3], &end, 16);
        if (!end || *end || parsed_fe8e > 0xff) return 2;
        parsed_fe8f = strtoul(argv[4], &end, 16);
        if (!end || *end || parsed_fe8f > 0xff) return 2;
    }
    signal(SIGINT, on_signal); signal(SIGTERM, on_signal);
    if (mkdir(argv[1], 0755) < 0 && errno != EEXIST) { perror("new output directory required"); return 2; }
    struct capture c = {.mutex = PTHREAD_MUTEX_INITIALIZER,
                        .changed = PTHREAD_COND_INITIALIZER,
                        .live_hook = live_hook || live_state, .live_state = live_state,
                        .target = (uint16_t)(live_state ? 0xfe8e : parsed_target),
                        .mask = (uint8_t)parsed_mask,
                        .requested_fe8e = (uint8_t)parsed_fe8e,
                        .requested_fe8f = (uint8_t)parsed_fe8f,
                        .hid_interface = -1};
    uvc_context_t *context = NULL;
    uvc_device_t *device = NULL;
    uvc_device_handle_t *handle = NULL;
    if (c.live_hook) {
        extern void hid_darwin_set_open_exclusive(int);
        if (hid_init() < 0) { fwprintf(stderr, L"HIDAPI init failed: %ls\n", hid_error(NULL)); return 1; }
        hid_darwin_set_open_exclusive(0);
        struct hid_device_info *hid_devices = hid_enumerate(0x534d, 0x2109);
        for (struct hid_device_info *info = hid_devices; info; info = info->next) {
            if (info->interface_number >= 0) {
                c.hid_interface = info->interface_number;
                break;
            }
        }
        hid_free_enumeration(hid_devices);
        if (c.hid_interface < 0) {
            fprintf(stderr, "Could not identify the MS2109 HID interface number.\n");
            hid_exit(); return 1;
        }
        c.hid = hid_open(0x534d, 0x2109, NULL);
        if (!c.hid) {
            fwprintf(stderr, L"Could not open MS2109 HID interface: %ls\n", hid_error(NULL));
            hid_exit(); return 1;
        }
        uint8_t id[3] = {0};
        for (unsigned i = 0; i < 3; i++)
            if (!xdata_read(&c, (uint16_t)(0xf800 + i), &id[i])) goto fail;
        if (id[0] != 0xa7 || id[1] != 0x10 || id[2] != 0x9a) {
            fprintf(stderr, "Unexpected silicon ID %02X%02X%02X.\n", id[0], id[1], id[2]);
            goto fail;
        }
        if (!read_stable_eeprom(&c, c.eeprom_sha256)) goto fail;
        if (c.eeprom_size != 2048 || strcmp(c.eeprom_sha256, expected_eeprom_sha256) != 0) {
            fprintf(stderr, "Unexpected EEPROM identity/size; refusing all register changes: size=%zu SHA-256=%s.\n",
                    c.eeprom_size, c.eeprom_sha256);
            goto fail;
        }
        uint8_t initial_block[16];
        if (!read_register_block(&c, initial_block)) goto fail;
        if (initial_block[0x0e] != 0 || initial_block[0x0f] != 0) {
            fprintf(stderr, "Unexpected FE8E/FE8F baseline %02X/%02X; refusing register changes.\n",
                    initial_block[0x0e], initial_block[0x0f]);
            goto fail;
        }
        c.original_fe8e = initial_block[0x0e];
        c.original_fe8f = initial_block[0x0f];
        c.original_valid = 1;
        char log_path[4096];
        snprintf(log_path, sizeof(log_path), "%s/live-register.jsonl", argv[1]);
        c.register_log = fopen(log_path, "wx");
        if (!c.register_log) { perror("register log"); goto fail; }
        fprintf(c.register_log,
                "{\"kind\":\"preflight\",\"chip_id\":\"%02X%02X%02X\",\"hid_interface\":%d,"
                "\"eeprom_size\":%zu,\"eeprom_sha256\":\"%s\","
                "\"register_block\":\"", id[0], id[1], id[2], c.hid_interface,
                c.eeprom_size, c.eeprom_sha256);
        for (unsigned i = 0; i < 16; i++) fprintf(c.register_log, "%s%02X", i ? " " : "", initial_block[i]);
        fprintf(c.register_log, "\"}\n"); fflush(c.register_log);
    }
    uvc_error_t error = uvc_init(&context, NULL);
    if (error < 0) { uvc_perror(error, "uvc_init"); return 1; }
    error = uvc_find_device(context, &device, 0x534d, 0x2109, NULL);
    if (error < 0) { uvc_perror(error, "find MS2109"); uvc_exit(context); return 1; }
    error = uvc_open(device, &handle);
    if (error < 0) { uvc_perror(error, "open MS2109"); uvc_unref_device(device); uvc_exit(context); return 1; }

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
    if (c.live_hook) {
        uint8_t after[16] = {0};
        if (!xdata_write(&c, 0xfe8e, c.original_fe8e) ||
            !xdata_write(&c, 0xfe8f, c.original_fe8f) ||
            !read_register_block(&c, after) || after[0x0e] != c.original_fe8e ||
            after[0x0f] != c.original_fe8f) {
            fprintf(stderr, "Final pre-run FE8E/FE8F restoration failed.\n");
            goto fail;
        }
        log_register_event(&c, "final-restore", 2, NULL, after, after[c.target - 0xfe80]);
    }
    uvc_close(handle); handle = NULL;
    uvc_unref_device(device); device = NULL;
    uvc_exit(context); context = NULL;
    if (c.live_hook) {
        uint8_t final_block[16] = {0};
        char final_eeprom[65] = {0};
        if (!reopen_hid(&c) || !read_register_block(&c, final_block) ||
            final_block[0x0e] != c.original_fe8e || final_block[0x0f] != c.original_fe8f) {
            fprintf(stderr, "Post-UVC FE8E/FE8F restoration readback failed.\n");
            goto fail;
        }
        if (!read_stable_eeprom(&c, final_eeprom) ||
            strcmp(final_eeprom, c.eeprom_sha256) != 0) {
            fprintf(stderr, "Post-UVC EEPROM fingerprint changed or could not be read.\n");
            goto fail;
        }
        fprintf(c.register_log,
                "{\"kind\":\"postflight\",\"eeprom_size\":%zu,\"eeprom_sha256\":\"%s\",\"register_block\":\"",
                c.eeprom_size, final_eeprom);
        for (unsigned i = 0; i < 16; i++) fprintf(c.register_log, "%s%02X", i ? " " : "", final_block[i]);
        fprintf(c.register_log, "\"}\n"); fflush(c.register_log);
        fprintf(stderr, "Post-UVC FE8E/FE8F restoration verified; EEPROM SHA-256 unchanged.\n");
    }
    if (c.register_log) fclose(c.register_log);
    if (c.hid) hid_close(c.hid);
    if (c.live_hook) hid_exit();
    fprintf(stderr, "Same-handle MJPEG then YUY2 sequence completed without SET_CUR.\n");
    return 0;
fail:
    if (handle) { uvc_close(handle); handle = NULL; }
    if (device) { uvc_unref_device(device); device = NULL; }
    if (context) { uvc_exit(context); context = NULL; }
    c.usb_handle = NULL;
    if (c.original_valid && reopen_hid(&c)) {
        uint8_t after_e = 0, after_f = 0;
        if (!xdata_write(&c, 0xfe8e, c.original_fe8e) ||
            !xdata_write(&c, 0xfe8f, c.original_fe8f) ||
            !xdata_read(&c, 0xfe8e, &after_e) || !xdata_read(&c, 0xfe8f, &after_f) ||
            after_e != c.original_fe8e || after_f != c.original_fe8f)
            fprintf(stderr, "FAIL-SAFE: could not verify original FE8E/FE8F restoration.\n");
        else fprintf(stderr, "Fail-safe: original FE8E/FE8F values restored and verified.\n");
        if (c.live_hook) {
            char recovery_eeprom[65] = {0};
            uint8_t recovered[16] = {0};
            int eeprom_ok = read_stable_eeprom(&c, recovery_eeprom) &&
                            strcmp(recovery_eeprom, c.eeprom_sha256) == 0;
            int block_ok = read_register_block(&c, recovered) &&
                           recovered[0x0e] == c.original_fe8e && recovered[0x0f] == c.original_fe8f;
            if (c.register_log) {
                fprintf(c.register_log,
                        "{\"kind\":\"recovery\",\"verified\":%s,\"eeprom_sha256\":\"%s\",\"register_block\":\"",
                        eeprom_ok && block_ok ? "true" : "false", recovery_eeprom);
                for (unsigned i = 0; i < 16; i++) fprintf(c.register_log, "%s%02X", i ? " " : "", recovered[i]);
                fprintf(c.register_log, "\"}\n"); fflush(c.register_log);
            }
            if (!eeprom_ok || !block_ok)
                fprintf(stderr, "FAIL-SAFE: post-recovery register/EEPROM verification failed.\n");
            else fprintf(stderr, "Fail-safe recovery verified; EEPROM SHA-256 unchanged.\n");
        }
    } else if (c.original_valid) fprintf(stderr, "FAIL-SAFE: HID reconnect failed before restoration.\n");
    if (c.register_log) fclose(c.register_log);
    if (c.hid) hid_close(c.hid);
    if (c.live_hook) hid_exit();
    if (c.metadata) fclose(c.metadata);
    if (c.requests) fclose(c.requests);
    return 1;
}
