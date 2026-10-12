"""Same-length startup calibration on the pinned, live-qualified firmware."""
import hashlib
from control_assembler import compact_stores
from release_builder import validate
BASE_SHA256='73201cd1a43864a2a32a3162b7ee453470bac649edd226ab683c2ba422e005dd'
PROCAM={'brightness':-17,'contrast':148,'hue':0,'saturation':146}
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
    image[50+n:52+n]=(sum(image[48:48+n])&65535).to_bytes(2,'big')
    validate(image)
    return bytes(image),bytes(image[48:48+n]),0xcc00
