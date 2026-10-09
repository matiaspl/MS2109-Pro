/*
 * Build a standards-shaped ICC v4 input profile for full-range BT.709 YCbCr
 * and insert it as one JPEG ICC APP2 segment. Only the bytes before SOS are
 * changed; quantization, Huffman, scan, and entropy-coded bytes are preserved.
 *
 * This is a decoder experiment. It is not evidence that a USB camera stack
 * recognizes the tag or that AVFoundation does.
 */
#include <lcms2.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void fail(const char *s) { fprintf(stderr, "%s\n", s); exit(2); }
static void log_error(cmsContext context, cmsUInt32Number code, const char *message) {
    (void)context; fprintf(stderr, "LittleCMS error %u: %s\n", code, message);
}
static void put16(FILE *f, unsigned n) { fputc((n >> 8) & 255, f); fputc(n & 255, f); }

static double inverse_oetf(double e) {
    return e < 0.081 ? e / 4.5 : pow((e + 0.099) / 1.099, 1.0 / 0.45);
}
static cmsInt32Number sample_ycbcr(const cmsUInt16Number in[], cmsUInt16Number out[], void *unused) {
    (void)unused;
    const double center = 128.0 / 255.0;
    double y = in[0] / 65535.0;
    double cb = in[1] / 65535.0 - center;
    double cr = in[2] / 65535.0 - center;
    double rp = y + 1.5748 * cr;
    double gp = y - 0.187324 * cb - 0.468124 * cr;
    double bp = y + 1.8556 * cb;
    double r = inverse_oetf(fmax(0.0, fmin(1.0, rp)));
    double g = inverse_oetf(fmax(0.0, fmin(1.0, gp)));
    double b = inverse_oetf(fmax(0.0, fmin(1.0, bp)));
    const double m[9] = {
        0.4360747, 0.3850649, 0.1430804,
        0.2225045, 0.7168786, 0.0606169,
        0.0139322, 0.0971045, 0.7141733
    };
    double xyz[3] = {m[0]*r+m[1]*g+m[2]*b,
                     m[3]*r+m[4]*g+m[5]*b,
                     m[6]*r+m[7]*g+m[8]*b};
    for (int i = 0; i < 3; i++) {
        double v = fmax(0.0, fmin(1.0, xyz[i]));
        out[i] = (cmsUInt16Number)lrint(v * 65535.0);
    }
    return 1;
}

static cmsHPROFILE make_profile(void) {
    cmsSetLogErrorHandler(log_error);
    cmsHPROFILE p = cmsCreateProfilePlaceholder(NULL);
    if (!p) fail("cmsCreateProfilePlaceholder failed");
    cmsSetProfileVersion(p, 4.4);
    cmsSetDeviceClass(p, cmsSigInputClass);
    cmsSetColorSpace(p, cmsSigYCbCrData);
    cmsSetPCS(p, cmsSigXYZData);
    cmsSetHeaderRenderingIntent(p, INTENT_PERCEPTUAL);
    cmsCIEXYZ d50 = {0.9642, 1.0, 0.8249};
    if (!cmsWriteTag(p, cmsSigMediaWhitePointTag, &d50)) fail("write wtpt failed");

    cmsMLU *desc = cmsMLUalloc(NULL, 1), *copy = cmsMLUalloc(NULL, 1);
    if (!desc || !copy) fail("cmsMLUalloc failed");
    cmsMLUsetASCII(desc, "en", "US", "BT.709 Full-Range YCbCr Input");
    cmsMLUsetASCII(copy, "en", "US", "Generated for decoder signaling test");
    if (!cmsWriteTag(p, cmsSigProfileDescriptionTag, desc) ||
        !cmsWriteTag(p, cmsSigCopyrightTag, copy)) fail("write text tags failed");

    cmsPipeline *pipe = cmsPipelineAlloc(NULL, 3, 3);
    cmsToneCurve *identity_curve = cmsBuildGamma(NULL, 1.0);
    cmsToneCurve *identity_curves[3] = {identity_curve, identity_curve, identity_curve};
    cmsStage *identity_in = cmsStageAllocToneCurves(NULL, 3, identity_curves);
    /* A 17^3 CLUT encodes the matrix + inverse OETF + D65-to-D50 PCS mapping
       without relying on a decoder's YCbCr convention. It stays below one
       JPEG APP2 segment while providing fine interpolation over code values. */
    cmsStage *clut = cmsStageAllocCLut16bit(NULL, 17, 3, 3, NULL);
    cmsStage *identity_out = cmsStageAllocToneCurves(NULL, 3, identity_curves);
    if (!pipe || !identity_curve || !identity_in || !clut || !identity_out ||
        !cmsStageSampleCLut16bit(clut, sample_ycbcr, NULL, 0))
        fail("allocate/sample YCbCr CLUT failed");
    if (!cmsPipelineInsertStage(pipe, cmsAT_BEGIN, identity_in) ||
        !cmsPipelineInsertStage(pipe, cmsAT_END, clut) ||
        !cmsPipelineInsertStage(pipe, cmsAT_END, identity_out) ||
        !cmsWriteTag(p, cmsSigAToB0Tag, pipe)) fail("write A2B0 pipeline failed");
    cmsPipelineFree(pipe);
    cmsFreeToneCurve(identity_curve);
    cmsMLUfree(desc);
    cmsMLUfree(copy);

    /* ICC v4 CICP tag: type signature, reserved bytes, primaries, transfer,
       matrix, videoFullRangeFlag. BT.709 full-range is (1,1,1,1). */
    static const uint8_t cicp[12] = {
        'c','i','c','p', 0,0,0,0, 1,1,1,1
    };
    if (!cmsWriteRawTag(p, (cmsTagSignature)0x63696370, cicp, sizeof(cicp)))
        fail("write CICP tag failed");
    return p;
}

static size_t scan_offset(const uint8_t *b, size_t n) {
    if (n < 4 || b[0] != 0xff || b[1] != 0xd8) fail("input lacks JPEG SOI");
    size_t i = 2;
    while (i + 4 <= n) {
        if (b[i++] != 0xff) fail("unexpected marker boundary before SOS");
        while (i < n && b[i] == 0xff) i++;
        if (i >= n) fail("truncated JPEG marker");
        uint8_t marker = b[i++];
        if (marker == 0xda) return i - 2;
        if (marker == 0xd9 || marker == 0x00) fail("unexpected marker before SOS");
        if (i + 2 > n) fail("truncated JPEG segment length");
        size_t len = ((size_t)b[i] << 8) | b[i + 1];
        if (len < 2 || i + len > n) fail("invalid JPEG segment length");
        i += len;
    }
    fail("JPEG SOS not found");
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 3) fail("Usage: test_jpeg_icc_signal INPUT.jpg OUTPUT.jpg");
    FILE *in = fopen(argv[1], "rb"); if (!in) fail("open input failed");
    if (fseek(in, 0, SEEK_END)) fail("seek failed");
    long l = ftell(in); if (l < 4 || fseek(in, 0, SEEK_SET)) fail("bad input length");
    size_t n = (size_t)l; uint8_t *src = malloc(n); if (!src) fail("allocation failed");
    if (fread(src, 1, n, in) != n) fail("read failed"); fclose(in);

    cmsHPROFILE profile = make_profile();
    cmsUInt32Number profile_size = 0;
    if (!cmsSaveProfileToMem(profile, NULL, &profile_size) || profile_size == 0)
        fail("profile size query failed");
    uint8_t *icc = malloc(profile_size); if (!icc) fail("profile allocation failed");
    if (!cmsSaveProfileToMem(profile, icc, &profile_size)) fail("profile serialization failed");
    cmsCloseProfile(profile);
    cmsHPROFILE reopened = cmsOpenProfileFromMem(icc, profile_size);
    if (!reopened || cmsGetColorSpace(reopened) != cmsSigYCbCrData ||
        cmsGetPCS(reopened) != cmsSigXYZData || !cmsIsTag(reopened, cmsSigAToB0Tag))
        fail("serialized ICC input profile failed validation");
    const cmsPipeline *a2b = (const cmsPipeline *)cmsReadTag(reopened, cmsSigAToB0Tag);
    if (!a2b) fail("serialized A2B0 tag could not be read");
    const uint8_t probes[][3] = {
        {0,128,128}, {255,128,128}, {128,128,128},
        {54,99,255}, {182,29,12}, {18,255,116}
    };
    for (size_t i = 0; i < sizeof(probes)/sizeof(probes[0]); i++) {
        cmsUInt16Number input[3], pcs[3];
        for (int c = 0; c < 3; c++) input[c] = (cmsUInt16Number)(probes[i][c] * 257u);
        cmsPipelineEval16(input, pcs, a2b);
        double xyz[3] = {pcs[0]/65535.0, pcs[1]/65535.0, pcs[2]/65535.0};
        if (i == 0 && (xyz[0] > .005 || xyz[1] > .005 || xyz[2] > .005))
            fail("A2B0 black endpoint is outside tolerance");
        if (i == 1 && (fabs(xyz[0]-.9642) > .01 || fabs(xyz[1]-1.0) > .01 || fabs(xyz[2]-.8249) > .01))
            fail("A2B0 white endpoint is outside tolerance");
        if (i == 2 && fabs(xyz[1]-.262) > .02)
            fail("A2B0 BT.709 neutral midtone is outside tolerance");
        if (i == 3 && (fabs(xyz[0]-.4361) > .025 || fabs(xyz[1]-.2225) > .025 || fabs(xyz[2]-.0139) > .025))
            fail("A2B0 BT.709 red primary is outside tolerance");
        fprintf(stderr, "A2B0 YCbCr %u,%u,%u -> PCS XYZ %.5f,%.5f,%.5f\n",
                probes[i][0], probes[i][1], probes[i][2],
                pcs[0]/65535.0, pcs[1]/65535.0, pcs[2]/65535.0);
    }
    cmsCloseProfile(reopened);
    if (profile_size + 14 + 2 > 65535) fail("ICC APP2 segment exceeds JPEG limit");
    size_t insert = scan_offset(src, n);
    FILE *out = fopen(argv[2], "wb"); if (!out) fail("open output failed");
    if (fwrite(src, 1, insert, out) != insert) fail("write prefix failed");
    fputc(0xff, out); fputc(0xe2, out); put16(out, (unsigned)(profile_size + 16));
    static const uint8_t id[12] = {'I','C','C','_','P','R','O','F','I','L','E',0};
    if (fwrite(id, 1, sizeof(id), out) != sizeof(id)) fail("write ICC id failed");
    fputc(1, out); fputc(1, out);
    if (fwrite(icc, 1, profile_size, out) != profile_size) fail("write ICC profile failed");
    if (fwrite(src + insert, 1, n - insert, out) != n - insert) fail("write source tail failed");
    if (fclose(out)) fail("close output failed");
    fprintf(stderr, "Inserted %u-byte ICC APP2 profile before SOS; preserved %zu source bytes after insertion.\n",
            profile_size, n - insert);
    free(icc); free(src); return 0;
}
