"""Pure offline EDID/USB metadata edits, preserving the supplied live image."""
from __future__ import annotations
import hashlib
from decimal import Decimal
from release_builder import validate, stores

TRANSFERS = {'bt709': 1, 'bt470m': 2, 'bt470bg': 3, 'srgb': 7}

def transfer_value(name, uvc_version):
    if uvc_version not in (0x0100, 0x0110, 0x0150):
        raise ValueError('Require a recognized advertised bcdUVC (0100, 0110, 0150)')
    value = TRANSFERS.get(name, name)
    if value not in TRANSFERS.values():
        raise ValueError('Unsupported transfer characteristic')
    if value == 7 and uvc_version < 0x0110:
        raise ValueError('sRGB transfer requires UVC 1.1 or newer')
    return value

def validate_edid(edid):
    if len(edid) != 256 or edid[:8] != bytes.fromhex('00ffffffffffff00') or edid[126] != 1:
        raise ValueError('Require the qualified two-block EDID')
    if any(sum(edid[i:i+128]) & 255 for i in (0,128)):
        raise ValueError('EDID checksum mismatch')

def edit_edid(edid, *, gamma=None, srgb=False):
    validate_edid(edid)
    if gamma is not None and srgb:
        raise ValueError('Choose gamma-only or the coherent sRGB profile')
    out = bytearray(edid)
    if gamma is not None:
        if edid[24] & 4:
            raise ValueError('Gamma-only trial would contradict existing sRGB flag')
        encoded = (Decimal(str(gamma)) - 1) * 100
        if encoded != encoded.to_integral_value() or not 0 <= encoded <= 254:
            raise ValueError('Gamma must be exactly representable in EDID')
        out[23] = int(encoded)
    if srgb:
        out[23] = 120
        out[24] |= 4
        # EDID coordinates: 10-bit fractions, nearest representable sRGB/D65.
        coords = [round(x*1024) for x in (.64,.33,.30,.60,.15,.06,.3127,.3290)]
        out[25] = sum((coords[i] & 3) << (6-2*i) for i in range(4))
        out[26] = sum((coords[i+4] & 3) << (6-2*i) for i in range(4))
        out[27:35] = bytes(x >> 2 for x in coords)
    out[127] = (-sum(out[:127])) & 255
    validate_edid(out)
    allowed = set(range(23,35)) | {127} if srgb else {23,127}
    if any(a != b and i not in allowed for i,(a,b) in enumerate(zip(edid,out))):
        raise AssertionError('Unexpected EDID field change')
    return bytes(out)

def byte_diff(before, after):
    return [{'offset': i, 'before': a, 'after': b} for i,(a,b) in enumerate(zip(before,after)) if a != b]

def finish_image(image, old_n, code):
    if len(image) != 2048 or len(code) > 1996:
        raise ValueError('Candidate exceeds the qualified 2 KiB EEPROM capacity')
    out = bytearray(image)
    out[2:4] = len(code).to_bytes(2,'big')
    out[48:] = bytes([255]) * (len(out)-48)
    out[48:48+len(code)] = code
    out[48+len(code):50+len(code)] = (sum(out[2:48]) & 65535).to_bytes(2,'big')
    out[50+len(code):52+len(code)] = (sum(code) & 65535).to_bytes(2,'big')
    validate(out)
    return bytes(out)

def edid_eeprom_candidate(image, baseline_edid, candidate_edid):
    """Extend the live-qualified gate-aware EDID routine; leave hooks in place."""
    n = validate(image)
    validate_edid(baseline_edid); validate_edid(candidate_edid)
    code = image[48:48+n]
    # The existing routine modifies VSDB and its checksum under F819.0.
    marker = bytes.fromhex('90fba27481f090fbff74bdf07d017f197ef812000e')
    if code.count(marker) != 1 or baseline_edid[162] != 0x81 or baseline_edid[255] != 0xbd:
        raise ValueError('Live image lacks the qualified gate-aware 8-bit EDID callback')
    changes = byte_diff(baseline_edid, candidate_edid)
    if any(r['offset'] not in set(range(23,35)) | {127} for r in changes):
        raise ValueError('Candidate changes fields beyond the color profile')
    patch = bytearray()
    for row in changes:
        patch.extend(stores(0xfb00 + row['offset'], [row['after']]))
    # Coalesce adjacent writes to respect EEPROM capacity.
    patch = bytearray(); i = 0
    while i < len(changes):
        first=changes[i]['offset']; values=[changes[i]['after']]; i += 1
        while i < len(changes) and changes[i]['offset'] == first + len(values):
            values.append(changes[i]['after']); i += 1
        patch.extend(stores(0xfb00+first, values))
    pos = code.index(marker) + 12
    # Marker length before the close-gate call is 12 bytes.
    if code[pos:pos+9] != bytes.fromhex('7d017f197ef812000e'):
        raise AssertionError('Gate marker insertion mismatch')
    result = finish_image(image,n,code[:pos]+patch+code[pos:])
    return result

def parse_configuration(data):
    if len(data) < 9 or data[1] not in (2,7) or int.from_bytes(data[2:4],'little') != len(data):
        raise ValueError('Incomplete USB configuration descriptor')
    offset=0; interface=None; version=None; colors=[]; fmt=None
    while offset < len(data):
        length=data[offset]
        if length < 2 or offset+length > len(data):
            raise ValueError('Malformed USB descriptor walk')
        d=data[offset:offset+length]
        if d[1] == 4:
            if length < 9: raise ValueError('Short interface descriptor')
            interface=(d[5],d[6]); fmt=None
        if d[1] == 0x24 and length >= 3:
            if interface == (14,1) and d[2] == 1:
                if length < 5: raise ValueError('Short VC header')
                version=int.from_bytes(d[3:5],'little')
            if interface == (14,2):
                if d[2] in (4,6): fmt='YUY2' if d[2] == 4 else 'MJPEG'
                if d[2] == 13:
                    if length != 6 or fmt is None: raise ValueError('Unqualified color record')
                    colors.append({'offset':offset,'format':fmt,'bytes':d.hex(),
                                   'primaries':d[3],'transfer':d[4],'matrix':d[5]})
        offset += length
    if version is None or sorted(r['format'] for r in colors) != ['MJPEG','YUY2']:
        raise ValueError('Require UVC header and one color record per MJPEG/YUY2 format')
    return {'bcdUVC':version,'colors':colors}

def transfer_eeprom_candidate(image, descriptor, ram_base, name):
    """Compact shared, fully guarded routine appended to the existing hook."""
    parsed=parse_configuration(descriptor); value=transfer_value(name,parsed['bcdUVC'])
    n=validate(image); code=bytearray(image[48:48+n])
    if all(r['transfer']==value for r in parsed['colors']):
        return bytes(image)
    if code[0] != 0x12:
        raise ValueError('Require the existing LCALL common-hook entry')
    # Both records must share exactly the six-byte signature for a shared guard.
    records=parsed['colors']; expected=bytes.fromhex(records[0]['bytes'])
    if any(bytes.fromhex(r['bytes']) != expected for r in records):
        raise ValueError('Color signatures differ; cannot use compact guard')
    from control_assembler import Asm
    base=0xcc00+n
    # Reviewed ROM-trampoline slots retired by rom_overlay.experiment_overlay.
    # Verify every original caller already targets ROM, not these four slots.
    retired=((0xd2a2,0x603c,0xd27f),(0xd2a6,0x5884,0xd28a),
             (0xd2aa,0x48e6,0xccc8),(0xd2ae,0x6069,0xcc28))
    pool=0xd2a2
    if code[pool-0xcc00:pool-0xcc00+16]!=b'\xff'*16:
        raise ValueError('Reviewed retired trampoline pool is occupied')
    for _,target,caller in retired:
        off=caller-0xcc00
        if code[off] not in (0x02,0x12) or code[off+1:off+3]!=target.to_bytes(2,'big'):
            raise ValueError('Retired trampoline caller has changed')
    prelude=Asm(pool); a=Asm(base)
    # Preserve observable state; original common helper sees original R7.
    prelude.call(int.from_bytes(code[1:3],'big'))
    for reg in (0xe0,0x82,0x83,0xd0): prelude.emit(0xc0,reg)
    prelude.emit(0x02,base>>8,base&255)
    for r in records:
        a.dptr(ram_base+r['offset']); a.call('guard')
    for reg in (0xd0,0x83,0x82,0xe0): a.emit(0xd0,reg)
    a.emit(0x22); a.label('guard')
    for i,v in enumerate(expected):
        if i: a.emit(0xa3)
        a.emit(0xe0); a.rel((0xb4,v),'guard_end')
    # At matrix byte: reset DPTR to preceding transfer byte using DPL only.
    # Verified color offsets do not cross a 256-byte boundary.
    for r in records:
        if (ram_base+r['offset']+4)>>8 != (ram_base+r['offset']+5)>>8:
            raise ValueError('Color field crosses a page')
    a.emit(0x15,0x82,0x74,value,0xf0); a.label('guard_end'); a.emit(0x22)
    code[1:3]=pool.to_bytes(2,'big')
    initial=prelude.finish()
    if len(initial)>16:raise ValueError('Trampoline pool overflow')
    code[pool-0xcc00:pool-0xcc00+len(initial)]=initial
    return finish_image(image,n,code+a.finish())

def manifest(before,after,**extra):
    return {'baseline_sha256':hashlib.sha256(before).hexdigest(),
            'candidate_sha256':hashlib.sha256(after).hexdigest(),
            'bytes':len(after),'changes':byte_diff(before,after), **extra}
