/* Capture packet boundaries before CoreAudio framing. No EEPROM/RAM writes.
 * macOS requires root or USB capture entitlement to detach its class driver.
 * Detach/re-attach may re-enumerate the entire MS2109 device on macOS.
 */
#include <libusb.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* Keep only 512 ms scheduled ahead to avoid distant macOS isoch frames. */
enum { PACKETS = 64, PACKET_BYTES = 256, TRANSFERS = 8, TOTAL_PACKETS = 4096 };
static FILE *pcm, *metadata;
static int pending, failures, stopping;
static unsigned packet_number;
static unsigned next_packet;
static unsigned char captured[TOTAL_PACKETS][PACKET_BYTES];
static unsigned lengths[TOTAL_PACKETS];
static int packet_status[TOTAL_PACKETS], transfer_status[TOTAL_PACKETS];
struct slot { unsigned first; int submitted; };
static struct slot slots[TRANSFERS];

static int submit(struct libusb_transfer *t) {
    struct slot *s = t->user_data;
    s->first = next_packet;
    int err = libusb_submit_transfer(t);
    if (err < 0) {
        fprintf(stderr, "Submit ISO starting at packet %u: %s (%d)\n",
                next_packet, libusb_error_name(err), err);
        return err;
    }
    next_packet += PACKETS;
    s->submitted = 1;
    pending++;
    return 0;
}

static void completed(struct libusb_transfer *t) {
    struct slot *s = t->user_data;
    s->submitted = 0;
    if (t->status != LIBUSB_TRANSFER_COMPLETED) {
        fprintf(stderr, "ISO completion at packet %u: status=%d\n", s->first, t->status);
        failures++;
        stopping = 1;
    }
    for (int i = 0; i < t->num_iso_packets; i++) {
        unsigned n = s->first + (unsigned)i;
        struct libusb_iso_packet_descriptor *p = &t->iso_packet_desc[i];
        transfer_status[n] = t->status;
        packet_status[n] = p->status;
        lengths[n] = p->actual_length;
        if (p->actual_length > PACKET_BYTES) { failures++; stopping = 1; }
        else if (p->actual_length)
            memcpy(captured[n], libusb_get_iso_packet_buffer_simple(t, i), p->actual_length);
        if (p->status != LIBUSB_TRANSFER_COMPLETED) failures++;
    }
    pending--;
    if (!stopping && next_packet < TOTAL_PACKETS && submit(t) < 0) {
        failures++;
        stopping = 1;
    }
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "Usage: %s OUTPUT_PREFIX\n", argv[0]);
        return 2;
    }
    for (int i = 0; i < TOTAL_PACKETS; i++) packet_status[i] = transfer_status[i] = -1;
    libusb_context *ctx = NULL;
    libusb_device_handle *dev = NULL;
    struct libusb_transfer *ts[TRANSFERS] = {0};
    int detached = 0, claimed = 0, rc = 1, err;
    char path[4096];
    snprintf(path, sizeof(path), "%s.pcm", argv[1]);
    pcm = fopen(path, "wx");
    snprintf(path, sizeof(path), "%s-packets.csv", argv[1]);
    metadata = fopen(path, "wx");
    if (!pcm || !metadata) { perror("create output (must not exist)"); goto done; }
    fprintf(metadata, "packet,transfer_status,length,packet_status\n");
    if ((err = libusb_init(&ctx)) < 0) goto error;
    dev = libusb_open_device_with_vid_pid(ctx, 0x534d, 0x2109);
    if (!dev) { fprintf(stderr, "Cannot open MS2109 534d:2109\n"); goto done; }
    fprintf(stderr, "MS2109: interface 3, alt 1, endpoint 82; queue 512 ms ahead\n");
    libusb_set_option(ctx, LIBUSB_OPTION_LOG_LEVEL, LIBUSB_LOG_LEVEL_WARNING);
    if (libusb_kernel_driver_active(dev, 3) == 1) {
        if ((err = libusb_detach_kernel_driver(dev, 3)) < 0) goto error;
        detached = 1;
    }
    if ((err = libusb_claim_interface(dev, 3)) < 0) goto error;
    claimed = 1;
    if ((err = libusb_set_interface_alt_setting(dev, 3, 0)) < 0) goto error;
    if ((err = libusb_set_interface_alt_setting(dev, 3, 1)) < 0) goto error;
    for (int i = 0; i < TRANSFERS; i++) {
        ts[i] = libusb_alloc_transfer(PACKETS);
        if (!ts[i]) { fprintf(stderr, "Allocation failed\n"); failures++; goto drain; }
        unsigned char *buffer = calloc(PACKETS, PACKET_BYTES);
        if (!buffer) { fprintf(stderr, "Buffer allocation failed\n"); failures++; goto drain; }
        libusb_fill_iso_transfer(ts[i], dev, 0x82, buffer,
            PACKETS * PACKET_BYTES, PACKETS, completed, &slots[i], 3000);
        libusb_set_iso_packet_lengths(ts[i], PACKET_BYTES);
        if ((err = submit(ts[i])) < 0) { failures++; goto drain; }
    }
    while (pending) {
        struct timeval timeout = {1, 0};
        if ((err = libusb_handle_events_timeout(ctx, &timeout)) < 0) {
            fprintf(stderr, "Handle USB events: %s (%d)\n", libusb_error_name(err), err);
            failures++;
            goto drain;
        }
    }
    /* Serialize in submission order even if completion callbacks reorder. */
    for (unsigned n = 0; n < next_packet; n++) {
        fprintf(metadata, "%u,%d,%u,%d\n", n, transfer_status[n], lengths[n], packet_status[n]);
        if (packet_status[n] == LIBUSB_TRANSFER_COMPLETED && lengths[n] <= PACKET_BYTES)
            if (fwrite(captured[n], 1, lengths[n], pcm) != lengths[n]) failures++;
        packet_number++;
    }
    if (!packet_number) failures++;
    rc = failures ? 1 : 0;
    fprintf(stderr, "Captured %u packets, failures=%d\n", packet_number, failures);
    goto done;
drain:
    stopping = 1;
    for (int i = 0; i < TRANSFERS; i++) if (ts[i] && slots[i].submitted) libusb_cancel_transfer(ts[i]);
    while (pending) {
        struct timeval timeout = {1, 0};
        libusb_handle_events_timeout(ctx, &timeout);
    }
    goto done;
error:
    fprintf(stderr, "USB error: %s (%d)\n", libusb_error_name(err), err);
done:
    if (claimed) {
        int reset = libusb_set_interface_alt_setting(dev, 3, 0);
        int release = libusb_release_interface(dev, 3);
        if (reset < 0 || release < 0) {
            fprintf(stderr, "Restore alt 0=%d, release interface=%d\n", reset, release);
            rc = 1;
        }
    }
    if (detached) {
        int attach = libusb_attach_kernel_driver(dev, 3);
        fprintf(stderr, "Reattach driver: %s (%d)\n", libusb_error_name(attach), attach);
        if (attach < 0) rc = 1;
    }
    for (int i = 0; i < TRANSFERS; i++) if (ts[i]) {
        free(ts[i]->buffer);
        libusb_free_transfer(ts[i]);
    }
    if (dev) libusb_close(dev);
    if (ctx) libusb_exit(ctx);
    if (pcm) fclose(pcm);
    if (metadata) fclose(metadata);
    fprintf(stderr, "Capture exit=%d, packet rows=%u\n", rc, packet_number);
    return rc;
}
