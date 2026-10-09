/* Synthetic libusb callbacks: exercise the real queue without USB access. */
#include <assert.h>
#include <libusb.h>
static int fail_submit;
static int fake_submit(struct libusb_transfer *t) {
    (void)t;
    return fail_submit ? LIBUSB_ERROR_INVALID_PARAM : 0;
}
#define libusb_submit_transfer fake_submit
#define main capture_program_main
#include "../tools/capture_audio_usb.c"
#undef main
#undef libusb_submit_transfer

static void fill_and_complete(struct libusb_transfer *t) {
    struct slot *s = t->user_data;
    t->status = LIBUSB_TRANSFER_COMPLETED;
    for (unsigned i = 0; i < PACKETS; i++) {
        t->iso_packet_desc[i].status = LIBUSB_TRANSFER_COMPLETED;
        t->iso_packet_desc[i].actual_length = s->first + i == 0 ? 2 : 192;
        memset(t->buffer + i * PACKET_BYTES, (s->first + i) & 255, PACKET_BYTES);
    }
    completed(t);
}

int main(void) {
    struct libusb_transfer *ts[TRANSFERS];
    for (int i = 0; i < TRANSFERS; i++) {
        ts[i] = libusb_alloc_transfer(PACKETS);
        assert(ts[i]);
        unsigned char *b = calloc(PACKETS, PACKET_BYTES);
        assert(b);
        libusb_fill_iso_transfer(ts[i], NULL, 0x82, b,
            PACKETS * PACKET_BYTES, PACKETS, completed, &slots[i], 3000);
        libusb_set_iso_packet_lengths(ts[i], PACKET_BYTES);
        assert(submit(ts[i]) == 0);
    }
    assert(pending == TRANSFERS && next_packet == PACKETS * TRANSFERS);
    /* Complete the first requests out of order, exercising slot reuse. */
    while (pending) {
        for (int i = TRANSFERS - 1; i >= 0; i--) {
            if (slots[i].submitted) fill_and_complete(ts[i]);
            assert(pending >= 0 && pending <= TRANSFERS);
            assert(next_packet <= TOTAL_PACKETS);
        }
    }
    assert(next_packet == TOTAL_PACKETS && failures == 0 && stopping == 0);
    for (unsigned n = 0; n < TOTAL_PACKETS; n++) {
        assert(packet_status[n] == LIBUSB_TRANSFER_COMPLETED);
        assert(lengths[n] == (n == 0 ? 2u : 192u));
        for (unsigned i = 0; i < lengths[n]; i++) assert(captured[n][i] == (n & 255));
    }
    /* A failed re-submit stops the queue and does not count as pending. */
    next_packet = 0;
    fail_submit = 1;
    assert(submit(ts[0]) == LIBUSB_ERROR_INVALID_PARAM);
    assert(next_packet == 0 && pending == 0 && slots[0].submitted == 0);
    for (int i = 0; i < TRANSFERS; i++) { free(ts[i]->buffer); libusb_free_transfer(ts[i]); }
    puts("Queue ordering, bounds, first half-frame preservation, and submission failure: PASS");
    return 0;
}
