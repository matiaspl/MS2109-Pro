"""Offline, checksum-validated neutral/calibrated MS2109 startup profiles."""
from pathlib import Path
import argparse
import hashlib
import json

ORIGINAL_SHA = '37103dccfc6c5e2062b6d22a0a619729449427270e52ae4332fde0da0f49dfe1'
ROM_SHA = 'b383ef31fca43ebc58a22be8e342d9a1e33ec1cc15afce02921910b0ca358bc8'
CALIBRATED = {'brightness_signed': -18, 'brightness_ui': 110,
              'contrast': 149, 'saturation': 147, 'hue': 0}
COLOR_RECORDS = (0xc2a4, 0xc43b)

def validate(b):
    if len(b) not in (2048, 4096) or b[:2] not in (b'\xa5\x5a', b'\x96\x69'):
        raise ValueError('Unknown EEPROM layout')
    n = int.from_bytes(b[2:4], 'big')
    if not 5 <= n <= len(b)-52:
        raise ValueError('Invalid code length')
    for start, end, check in ((2,48,48+n), (48,48+n,50+n)):
        if sum(b[start:end]) & 65535 != int.from_bytes(b[check:check+2], 'big'):
            raise ValueError('EEPROM checksum mismatch')
    return n

def set_usb_names(image, video_name=None, audio_name=None):
    """Update the ROM-consumed video/audio EEPROM header string records."""
    if video_name is None and audio_name is None:
        return image
    out = bytearray(image)
    n = validate(out)
    for offset, label, name in ((0x10, 'video', video_name),
                                (0x20, 'audio', audio_name)):
        if name is None:
            continue
        if not isinstance(name, str):
            raise ValueError(f'{label} name must be a string')
        try:
            encoded = name.encode('ascii')
        except UnicodeEncodeError as error:
            raise ValueError(f'{label} name must use ASCII characters') from error
        if not encoded or len(encoded) > 15:
            raise ValueError(f'{label} name must contain 1 to 15 ASCII bytes')
        # Header record: one byte for the total record length (prefix plus
        # text), up to 15 ASCII bytes, then FF padding to the fixed 16-byte field.
        out[offset:offset+16] = (bytes((len(encoded)+1,)) + encoded +
                                 bytes((0xFF,)) * (15-len(encoded)))
    checksum_offset = 48 + n
    out[checksum_offset:checksum_offset+2] = (sum(out[2:48]) & 0xFFFF).to_bytes(2, 'big')
    validate(out)
    return bytes(out)

def stores(addr, values):
    out = bytearray([0x90, addr >> 8, addr & 255])
    for i, v in enumerate(values):
        if i:
            out.append(0xa3)
        out.extend((0x74,v,0xf0))
    return out

def matrix_patch():
    """Only change a recognized color descriptor, never adjacent frame bytes.

    Stage 1 corrects declarations before USB interrupts are enabled. Stage 2
    repairs them if configuration RAM is rebuilt. Preserve primaries/transfer.
    Other-speed descriptors served directly from mask ROM are outside this
    qualified high-speed RAM patch.
    """
    output = bytearray()
    for addr in COLOR_RECORDS:
        block = bytearray([0x90, addr >> 8, addr & 255])
        branches = []
        for i, value in enumerate(bytes.fromhex('06 24 0d 01 01 04')):
            if i: block.append(0xa3)  # INC DPTR
            block.extend((0xe0, 0xb4, value, 0))  # MOVX A,@DPTR; CJNE A,#value,end
            branches.append(len(block)-1)
        block.extend((0x74, 1, 0xf0))  # DPTR still points to bMatrixCoefficients
        for branch in branches:
            block[branch] = len(block)-(branch+1)
        output.extend(block)
    return bytes(output)


def build(b, channel_order=False, calibrated_color=False, rom=None,
          calibrated_color_v2=False, uvc_control_profile=False, uvc_control_edid="custom",
          release_layout=False, product_name=None, video_name=None, audio_name=None):
    if release_layout and (not uvc_control_profile or uvc_control_edid != 'rom'):
        raise ValueError('Compact control repair requires --uvc_control-profile --uvc_control-edid rom')
    if uvc_control_edid != "custom" and not uvc_control_profile:
        raise ValueError("EDID selection requires the uvc_control profile")
    if uvc_control_profile:
        if product_name is not None:
            raise ValueError('Product-name editing is not yet packed into the compact control-repair profile')
        if channel_order or calibrated_color or calibrated_color_v2:
            raise ValueError('Control repair is a complete profile; do not combine profile flags')
        if rom is None:
            raise ValueError('Control-repair profile requires the qualified mask ROM')
        from control_assembler import assemble
        if release_layout:
            from release_layout import assemble_compact
            prototype = assemble_compact(b, rom)
        else:
            prototype = assemble(b, rom, edid_source=uvc_control_edid)
        image = prototype.eeprom(b)
        image = set_usb_names(image, video_name, audio_name)
        return image, prototype.overlay, 0xCC00
    n = validate(b)
    if hashlib.sha256(b).hexdigest() != ORIGINAL_SHA:
        raise ValueError('This patch is qualified only for the backed-up connected dongle')
    if b[48] != 0x90 or b[51:53] != b'\xef\xf0' or not b[4] & 1:
        raise ValueError('Unexpected Patch_Common hook')
    if calibrated_color and calibrated_color_v2:
        raise ValueError('Choose one calibrated color profile')
    if product_name is not None and calibrated_color_v2:
        raise ValueError('Product-name hook requires the stage-2 calibrated profile')
    product_descriptor = None
    if product_name is not None:
        if not isinstance(product_name, str) or not product_name:
            raise ValueError('USB product name must not be empty')
        product_payload = product_name.encode('utf-16le')
        if len(product_payload) + 2 > 255:
            raise ValueError('USB product string descriptor is too long')
        product_descriptor = bytes((len(product_payload) + 2, 3)) + product_payload
    # Stage 1 occurs after ROM 4d54 initializes current state + hardware.
    calibrated = calibrated_color or calibrated_color_v2
    if calibrated:
        if rom is None or hashlib.sha256(rom).hexdigest() != ROM_SHA:
            raise ValueError('Calibrated descriptor offsets require the qualified MS2109 ROM')
        for addr in COLOR_RECORDS:
            if rom[addr:addr+6] != bytes.fromhex('06 24 0d 01 01 04'):
                raise ValueError('Unexpected saved color descriptor')
    # Signed UVC brightness is a little-endian int16, hardware is signed8.
    procamp = stores(0xc6a0, [0xee,0xff,149,0,0,0,147,0]) if calibrated else stores(0xc6a0, [0,0,128,0,0,0,128,0])
    procamp += stores(0xfe90, [0xee,149,147,0]) if calibrated else stores(0xfe90, [0,128,128,0])
    if calibrated_color:
        procamp += matrix_patch()
    product_call_offset = None
    matrix_call_offset = None
    # Stage 2: exact same descriptor fields as the specified upstream patch.
    stereo = stores(0xc4c5, [2]) + stores(0xc4c9, [0x80,0xbb,0])
    # Qualified with the Mac HDMI source: FE60=01 routes continuous source L
    # to USB L and gapped source R to USB R. This does not correct sample skew.
    if channel_order:
        stereo += stores(0xfe60, [1])
    if calibrated_color:
        stereo += matrix_patch()
    if product_descriptor is not None:
        # ROM boot calls stage 1 immediately before its product-string builder
        # at 22DC, which overwrites C636. Stage 2 runs from the later poll loop;
        # repair the generated response there so it survives enumeration.
        product_call_offset = len(stereo)
        stereo += b'\x12\x00\x00'
    # CJNE uses SIGNED relative displacement; a 128..255-byte block would
    # silently branch backward. Use a forward LJMP for larger stage bodies.
    def stage(number, body, start):
        if len(body) <= 127:
            return bytes([0xef,0xb4,number,len(body)]) + body
        target = start+9+len(body)
        return bytes([0xef,0xb4,number,2,0x80,3,0x02,target>>8,target&255]) + body
    dest = 0xcc00+n+4
    if calibrated_color_v2:
        # Retain both runtime patch points, but share one guarded routine.
        first = bytearray(stage(1,procamp + (b'' if product_descriptor is not None else b'\x12\x00\x00'),dest))
        second = bytearray(stage(2,stereo + b'\x12\x00\x00',dest+len(first)))
        helper = dest + len(first) + len(second) + 4
        first_header = len(first) - len(procamp)
        if product_descriptor is None:
            first[-2:] = helper.to_bytes(2,'big')
        else:
            first[first_header+matrix_call_offset+1:first_header+matrix_call_offset+3] = helper.to_bytes(2,'big')
        second[-2:] = helper.to_bytes(2,'big')
        patch = bytearray(first + second + b[48:51] + b'\x22')
        if dest + len(patch) != helper:
            raise AssertionError('Shared matrix helper address calculation failed')
        patch += matrix_patch() + b'\x22'
    else:
        first = stage(1,procamp,dest)
        second = stage(2,stereo,dest+len(first))
        second_header = len(second)-len(stereo)
        patch = bytearray(first)
        patch += second
        patch += b[48:51] + b'\x22'  # displaced MOV DPTR, then RET
    if product_descriptor is not None:
        product_helper = dest + len(patch)
        call_offset = len(first) + second_header + product_call_offset
        patch[call_offset+1:call_offset+3] = product_helper.to_bytes(2,'big')
        source = product_helper + 18
        patch.extend(bytes((0x7b,0xff,0x7a,(source>>8)&255,0x79,source&255,
                            0x7c,0,0x7d,len(product_descriptor),0x7e,0xc6,0x7f,0x36,
                            0x12,0x50,0x38,0x22)))
        patch.extend(product_descriptor)
    # Preserve old checksums as upstream does; append only into erased EEPROM.
    off = 48+n+4
    if off+len(patch)+4 > len(b) or any(v != 255 for v in b[off:off+len(patch)+4]):
        raise ValueError('Insufficient erased space for patch')
    out = bytearray(b)
    out[off:off+len(patch)] = patch
    out[48:51] = bytes([0x12,dest>>8,dest&255])
    new_n = n+4+len(patch)
    out[2:4] = new_n.to_bytes(2,'big')
    out[48+new_n:50+new_n] = (sum(out[2:48]) & 65535).to_bytes(2,'big')
    out[50+new_n:52+new_n] = (sum(out[48:48+new_n]) & 65535).to_bytes(2,'big')
    validate(out)
    image = set_usb_names(bytes(out), video_name, audio_name)
    return image, bytes(patch), dest

