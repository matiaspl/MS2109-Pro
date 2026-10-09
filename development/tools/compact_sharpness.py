"""Relocatable, branch-relaxed MS2109 control-repair profile (offline only)."""
from dataclasses import dataclass
import hashlib

from sharpness_firmware import (BASE, MAX_CODE, DESC_BUFFER, VIDEO_HELPER, Prototype,
                                common_code, main_code, descriptor_code)
from audit_factory_space import experiment_overlay, load_inputs


@dataclass
class Node:
    kind: str
    data: bytes = b''
    target: object = None
    name: str = ''

    def minimum(self):
        if self.kind == 'label': return 0
        if self.kind == 'raw': return len(self.data)
        if self.kind == 'absolute': return 2 if self.data == b'\x12' else 3
        return 2 if self.kind == 'jump' else len(self.data)+1

    def maximum(self):
        if self.kind in ('raw','label'): return self.minimum()
        if self.kind == 'absolute': return 3
        if self.kind == 'jump': return 3
        return len(self.data) + (4 if self.data[0] in INVERSE else 6)


INVERSE = {0x20:0x30, 0x30:0x20, 0x40:0x50, 0x50:0x40, 0x60:0x70, 0x70:0x60}


class LinkAsm:
    def __init__(self, origin=0): self.nodes=[]
    def label(self,name): self.nodes.append(Node('label',name=name))
    def emit(self,*data): self.raw(bytes(data))
    def raw(self,data): self.nodes.append(Node('raw',bytes(data)))
    def absolute(self,opcode,target): self.nodes.append(Node('absolute',bytes((opcode,)),target))
    def call(self,target): self.absolute(0x12,target)
    def dptr(self,target): self.absolute(0x90,target)
    def jump(self,target): self.nodes.append(Node('jump',target=target))
    def rel(self,opcode,target):
        if tuple(opcode)==(0x80,): self.jump(target)
        else: self.nodes.append(Node('conditional',bytes(opcode),target))
    def far_if(self,opcode,target): self.rel(opcode,target)


def split(nodes, names):
    result={};current=None
    for node in nodes:
        if node.kind=='label' and node.name in names:
            current=node.name;result[current]=[]
        if current is None:raise ValueError('First node is not a fragment label')
        result[current].append(node)
    return result


def fragments():
    common=LinkAsm();common_code(common,compact=True)
    main=main_code(0,include_common=False,include_descriptor=False,
                   bank_zero=True,assembler=LinkAsm)
    video=LinkAsm();video.label('video');video.label('factory_video');video.raw(VIDEO_HELPER)
    descriptor=LinkAsm();descriptor_code(descriptor,compact=True)
    units = (split(common.nodes,('common','matrix')) |
             split(main.nodes,('cc10','usb')) |
             {'video':video.nodes,'descriptor':descriptor.nodes})
    for node in units['cc10']:
        if node.kind=='raw':
            node.data=node.data.replace(bytes.fromhex('e8c0e0'), bytes.fromhex('c000'))
            node.data=node.data.replace(bytes.fromhex('d0e0f8'), bytes.fromhex('d000'))
    # A nearby delegation trampoline keeps guards short.
    for node in units['usb']:
        if node.target == 'delegate':
            node.target='usb_'+node.target
    units['usb'] += [Node('label',name='usb_delegate'),Node('jump',target='delegate')]
    nodes=[]
    for node in units['descriptor']:
        if node.kind=='label' and node.name=='descriptor_copy':
            nodes += [Node('jump',target='descriptor_copy'),
                      Node('label',name='descriptor_delegate'),Node('jump',target='delegate')]
        if node.target=='delegate':node.target='descriptor_delegate'
        nodes.append(node)
    units['descriptor']=nodes
    return units



# Old CC10 helper is bypassed by the new CC10 LJMP. Padding CC1F included once.
# The 14-byte alternate startup is deliberately retained. Its trailing two-byte
# spin loop stays at D2B2; only the obsolete checksum pair after it is omitted.
POOLS=((0xCC13,13),(0xCD52,256),(0xCFAC,142),(0xD201,55),(0xD2A2,16),(0xD2B4,None))


def link(units, assignment):
    sizes={name:[node.maximum() for node in nodes] for name,nodes in units.items()}
    addresses={};symbols={};origins={}
    for iteration in range(40):
        symbols={};origins={};addresses={};ends=[]
        for (base,limit),names in zip(POOLS,assignment):
            cursor=base
            for name in names:
                origins[name]=cursor
                for i,node in enumerate(units[name]):
                    addresses[name,i]=cursor
                    if node.kind=='label':symbols[node.name]=cursor
                    cursor+=sizes[name][i]
            ends.append(cursor)
        changed=False
        for name,nodes in units.items():
            for i,node in enumerate(nodes):
                if node.kind not in ('jump','conditional','absolute'):continue
                target=symbols[node.target] if isinstance(node.target,str) else node.target
                displacement=target-(addresses[name,i]+node.minimum())
                same_page=(addresses[name,i]+2)&0xF800 == target&0xF800
                if node.kind=='absolute':
                    wanted=2 if node.data==b'\x12' and same_page else 3
                else:
                    short=-128<=displacement<=127 or (node.kind=='jump' and same_page)
                    wanted=node.minimum() if short else node.maximum()
                if wanted!=sizes[name][i]:sizes[name][i]=wanted;changed=True
        if not changed:break
    else:return None  # An oscillating layout is not a valid packing candidate.
    if any(limit is not None and end>base+limit for (base,limit),end in zip(POOLS,ends)):
        return None
    output={}
    for name,nodes in units.items():
        out=bytearray()
        for i,node in enumerate(nodes):
            at=origins[name]+len(out)
            if node.kind=='label':continue
            if node.kind=='raw':out.extend(node.data);continue
            target=symbols[node.target] if isinstance(node.target,str) else node.target
            if node.kind=='absolute':
                if sizes[name][i]==2:out.extend(bytes((0x11|((target>>3)&0xE0),target&255)))
                else:out.extend(node.data+target.to_bytes(2,'big'))
                continue
            if sizes[name][i]==node.minimum():
                displacement=target-at-node.minimum()
                if node.kind=='jump' and not -128<=displacement<=127:
                    out.extend(bytes((0x01|((target>>3)&0xE0),target&255)))
                else:
                    out.extend((b'\x80' if node.kind=='jump' else node.data)+bytes((displacement&255,)))
            elif node.kind=='jump':out.extend(b'\x02'+target.to_bytes(2,'big'))
            elif node.data[0] in INVERSE:
                out.extend(bytes((INVERSE[node.data[0]],))+node.data[1:]+b'\x03\x02'+target.to_bytes(2,'big'))
            else:
                out.extend(node.data+b'\x02\x80\x03\x02'+target.to_bytes(2,'big'))
        assert len(out)==sum(sizes[name])
        output[name]=bytes(out)
    return origins,symbols,output,ends


def pack(units):
    # Explore assignments using minimum sizes as a lower bound; retain all
    # conditional guards, then validate the actual relaxed lengths afterward.
    names=sorted(units,key=lambda name:-sum(node.minimum() for node in units[name]))
    minimum={name:sum(node.minimum() for node in units[name]) for name in names}
    assignment=[[] for _ in POOLS];used=[0]*len(POOLS)
    best=None;best_end=0xE000;attempts=0
    def visit(index):
        nonlocal best,best_end,attempts
        if POOLS[-1][0]+used[-1]>=best_end:return
        if index==len(names):
            attempts+=1;candidate=link(units,assignment)
            if candidate and candidate[-1][-1]<best_end:
                best=candidate;best_end=candidate[-1][-1]
            return
        name=names[index];count=minimum[name]
        for pool,(_,limit) in enumerate(POOLS):
            if limit is not None and used[pool]+count>limit:continue
            assignment[pool].append(name);used[pool]+=count
            visit(index+1)
            used[pool]-=count;assignment[pool].pop()
    visit(0)
    if best is None:raise ValueError('No non-overlapping layout found')
    return best,attempts


def assemble_compact(original,rom):
    pinned_original,pinned_rom,_=load_inputs()
    if original!=pinned_original or rom!=pinned_rom:raise ValueError('Unqualified inputs')
    if rom[0x714A:0x7152]!=bytes.fromhex('0b24050201000002'):
        raise ValueError('ROM PU identity changed')
    units=fragments()
    (origins,symbols,code,ends),attempts=pack(units)
    body=bytearray(experiment_overlay())
    body[0x152:0x252]=b'\xff'*256
    body[0x13:0x20]=b'\xff'*13
    body[0x51B],body[0x51D]=0x77,0x38
    size=ends[-1]-BASE
    body.extend(b'\xff'*(size-len(body)))
    for name,data in code.items():
        offset=origins[name]-BASE
        body[offset:offset+len(data)]=data
    body[:3]=b'\x12'+symbols['common'].to_bytes(2,'big')
    body[0x10:0x13]=b'\x02'+symbols['cc10'].to_bytes(2,'big')
    report={
        'status':'offline compact candidate; not hardware-qualified',
        'startup_procamp':{'brightness_signed':-18,'contrast':149,
                           'hue':0,'saturation':148},
        'get_def':{'status':'CC10 hook returns the startup procamp defaults',
                   'brightness_signed':-18,'contrast':149,
                   'hue':0,'saturation':148},
        'edid_source':'rom','optimized':True,
        'eeprom_limit_bytes':2048,'code_limit_bytes':MAX_CODE,
        'required_code_bytes':len(body),'deficit_bytes':max(0,len(body)-MAX_CODE),
        'required_image_bytes':len(body)+52,'free_eeprom_bytes':max(0,MAX_CODE-len(body)),
        'overlay_sha256':hashlib.sha256(body).hexdigest(),
        'original_sha256':hashlib.sha256(original).hexdigest(),
        'rom_sha256':hashlib.sha256(rom).hexdigest(),
        'rollback':'artifacts/ms2109-calibrated-stereo-channel-order.bin',
        'packing_candidates_evaluated':attempts,
        'fragments':{name:{'start':hex(origins[name]),'size':len(data),
                           'kind':'code'} for name,data in code.items()},
        'pool_usage':[{'start':hex(base),'capacity':limit,'used':end-base}
                      for (base,limit),end in zip(POOLS,ends)],
        'memory':{'overlay':[hex(BASE),hex(BASE+len(body)-1)],
                  'descriptor_buffer':[hex(DESC_BUFFER),hex(DESC_BUFFER+1211-1)],
                  'edid_buffer':None,'ep0_staging_rom_owned':['0xc020','0xc021']},
        'symbols':{name:hex(value) for name,value in symbols.items()},
        'limitations':['Offline instruction/branch validation does not establish hardware timing or reentrancy',
                       'Descriptor scratch and interrupt stack ownership require qualification',
                       'Stock ROM USB calls require register bank zero'],
    }
    return Prototype(bytes(body),symbols,report)


if __name__=='__main__':
    import json
    original,rom,_=load_inputs()
    print(json.dumps(assemble_compact(original,rom).report,indent=2))
