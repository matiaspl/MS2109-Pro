/* Decode JPEG samples without a YCbCr-to-RGB matrix or range conversion.
 * Originals remain untouched. libjpeg performs IDCT and chroma upsampling only.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#include <jpeglib.h>

struct error_state { struct jpeg_error_mgr base; jmp_buf jump; };
static void fail(j_common_ptr c) {
    struct error_state *e = (struct error_state *)c->err;
    (*c->err->output_message)(c);
    longjmp(e->jump, 1);
}
int main(int argc, char **argv) {
    if (argc != 4) {
        fprintf(stderr, "Usage: decode_jpeg_ycbcr INPUT.jpg NEW_OUTPUT.ycbcr NEW_METADATA.json\n");
        return 2;
    }
    FILE *input = fopen(argv[1], "rb");
    if (!input) { perror("input"); return 1; }
    struct jpeg_decompress_struct c = {0};
    struct error_state e;
    c.err = jpeg_std_error(&e.base); e.base.error_exit = fail;
    /* Outputs are created only after header validation. On decoder failure,
     * an incomplete buffer has no matching successful metadata file. */
    if (setjmp(e.jump)) { jpeg_destroy_decompress(&c); fclose(input); return 1; }
    jpeg_create_decompress(&c);
    jpeg_save_markers(&c, JPEG_APP0 + 2, 65535);
    jpeg_stdio_src(&c, input);
    jpeg_read_header(&c, TRUE);
    if (c.jpeg_color_space != JCS_YCbCr || c.num_components != 3 ||
        c.image_width != 1920 || c.image_height != 1080 || c.data_precision != 8) {
        fprintf(stderr, "Expected 1920x1080 8-bit YCbCr JPEG, got %ux%u space=%d components=%d\n",
                c.image_width, c.image_height, c.jpeg_color_space, c.num_components);
        jpeg_destroy_decompress(&c); fclose(input); return 1;
    }
    unsigned icc_markers = 0;
    for (jpeg_saved_marker_ptr m = c.marker_list; m; m = m->next)
        if (m->marker == JPEG_APP0 + 2 && m->data_length >= 12 &&
            !memcmp(m->data, "ICC_PROFILE\0", 12)) ++icc_markers;
    int sampling[3][3];
    for (int i = 0; i < 3; ++i) {
        sampling[i][0] = c.comp_info[i].component_id;
        sampling[i][1] = c.comp_info[i].h_samp_factor;
        sampling[i][2] = c.comp_info[i].v_samp_factor;
    }
    int jfif = c.saw_JFIF_marker, adobe = c.saw_Adobe_marker;
    int adobe_transform = c.Adobe_transform;
    c.out_color_space = JCS_YCbCr; c.dct_method = JDCT_ISLOW;
    c.do_fancy_upsampling = TRUE;
    jpeg_start_decompress(&c);
    FILE *output = fopen(argv[2], "wx");
    if (!output) { perror("new output"); jpeg_destroy_decompress(&c); fclose(input); return 1; }
    JSAMPARRAY row = (*c.mem->alloc_sarray)((j_common_ptr)&c, JPOOL_IMAGE, c.output_width * 3, 1);
    int io_error = 0;
    while (c.output_scanline < c.output_height) {
        jpeg_read_scanlines(&c, row, 1);
        if (fwrite(row[0], 1, c.output_width * 3, output) != c.output_width * 3) { io_error = 1; break; }
    }
    if (fclose(output)) io_error = 1;
    if (io_error) { perror("write"); jpeg_destroy_decompress(&c); fclose(input); return 1; }
    jpeg_finish_decompress(&c);
    FILE *meta = fopen(argv[3], "wx");
    if (!meta) { perror("new metadata"); jpeg_destroy_decompress(&c); fclose(input); return 1; }
    fprintf(meta, "{\"width\":%u,\"height\":%u,\"components\":3,\"pixel_format\":\"YCbCr-interleaved\","
            "\"decoder\":\"libjpeg-turbo\",\"idct\":\"JDCT_ISLOW\",\"rgb_conversion\":false,\"range_conversion\":false,"
            "\"jfif_marker\":%s,\"adobe_marker\":%s,\"adobe_transform\":%d,\"icc_markers\":%u,\"warnings\":%ld,"
            "\"sampling\":[[%d,%d,%d],[%d,%d,%d],[%d,%d,%d]]}\n",
            c.image_width, c.image_height, jfif ? "true" : "false", adobe ? "true" : "false",
            adobe_transform, icc_markers, c.err->num_warnings,
            sampling[0][0], sampling[0][1], sampling[0][2], sampling[1][0], sampling[1][1], sampling[1][2],
            sampling[2][0], sampling[2][1], sampling[2][2]);
    int rc = fclose(meta) ? 1 : 0;
    jpeg_destroy_decompress(&c); fclose(input); return rc;
}
