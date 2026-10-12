"""Startup calibration and removal of the qualified EDID restriction."""
import hashlib
from control_assembler import compact_stores
from release_builder import validate
BASE_SHA256='73201cd1a43864a2a32a3162b7ee453470bac649edd226ab683c2ba422e005dd'
PROCAM={'brightness':-17,'contrast':148,'hue':0,'saturation':146}
# Retire the complete gate-aware EDID callback in place. Keep its entry address
# and all following addresses stable: callers return immediately, with no RAM
# writes or register changes. The remaining bytes are unreachable NOP padding.
EDID_8BIT_CALLBACK=bytes.fromhex(
    'c0e0c0d0c082c083c003c004c005c006c00753d0e7750401750501'
    '7f197ef812701890fba27481f090fbff74bdf07d017f197ef812000e'
    'd007d006d005d004d003d083d082d0d0d0e022')
def build_qualified_release(base):
    if hashlib.sha256(base).hexdigest()!=BASE_SHA256:
        raise ValueError('Qualified baseline image hash mismatch')
    n=validate(base); image=bytearray(base)
    for addr,old,new in [(0xc6a0,[0xee,0xff,149,0,0,0,147,0],[0xef,0xff,148,0,0,0,146,0]),(0xfe90,[0xee,149,147,0],[0xef,148,146,0])]:
        before=compact_stores(addr,old);after=compact_stores(addr,new)
        if base.count(before)!=1 or len(before)!=len(after):
            raise ValueError('Require unique, same-length qualified startup routine')
        pos=base.index(before)
        if not 48<=pos<48+n-len(before)+1:raise ValueError('Startup routine outside overlay')
        image[pos:pos+len(before)]=after
    if base.count(EDID_8BIT_CALLBACK)!=1:
        raise ValueError('Require the unique qualified 8-bit EDID callback')
    pos=base.index(EDID_8BIT_CALLBACK)
    if pos+len(EDID_8BIT_CALLBACK)!=48+n:
        raise ValueError('EDID callback differs from the pinned overlay layout')
    image[pos:pos+len(EDID_8BIT_CALLBACK)]=b'\x22'+bytes(len(EDID_8BIT_CALLBACK)-1)
    image[50+n:52+n]=(sum(image[48:48+n])&65535).to_bytes(2,'big')
    validate(image)
    return bytes(image),bytes(image[48:48+n]),0xcc00
