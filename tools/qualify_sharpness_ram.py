"""Run the compact Sharpness profile as a reversible volatile RAM overlay.

This tool verifies the installed EEPROM before touching XDATA, snapshots every
range the candidate or its callback can change, and restores those ranges on
all normal Python exits. It never issues EEPROM writes.
"""
from __future__ import annotations
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import subprocess
import time

from ms2109_hid import Device
from build_patch import validate

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts/sharpness-firmware/20261007-compact-final"
EXPECTED_EEPROM = "83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82"
EXPECTED_CANDIDATE = "d6c1c53fa43e8f4d622c37022fbd91a6bd093813af81585172750380071da596"
OVERLAY_START, OVERLAY_LENGTH = 0xCC00, 1994
DESC_START, DESC_LENGTH = 0xD800, 1211


class UVC:
    """Minimal libusb EP0 class-control transport; no interface claim/detach."""
    def __init__(self):
        self.lib = C.CDLL("/opt/homebrew/lib/libusb-1.0.dylib")
        self.lib.libusb_init.argtypes = [C.POINTER(C.c_void_p)]
        self.lib.libusb_init.restype = C.c_int
        self.lib.libusb_open_device_with_vid_pid.argtypes = [C.c_void_p,C.c_uint16,C.c_uint16]
        self.lib.libusb_open_device_with_vid_pid.restype = C.c_void_p
        self.lib.libusb_control_transfer.argtypes = [C.c_void_p,C.c_uint8,C.c_uint8,
            C.c_uint16,C.c_uint16,C.POINTER(C.c_ubyte),C.c_uint16,C.c_uint]
        self.lib.libusb_control_transfer.restype = C.c_int
        self.lib.libusb_close.argtypes = [C.c_void_p]
        self.lib.libusb_exit.argtypes = [C.c_void_p]
        self.ctx = C.c_void_p()
        rc = self.lib.libusb_init(C.byref(self.ctx))
        if rc: raise RuntimeError(f"libusb_init failed: {rc}")
        self.handle = self.lib.libusb_open_device_with_vid_pid(self.ctx,0x534d,0x2109)
        if not self.handle:
            self.close()
            raise RuntimeError("libusb could not open the enumerated MS2109 for EP0 controls")

    def transfer(self, bm, request, value, index, length, payload=b""):
        buf=(C.c_ubyte*max(length,len(payload),1))()
        for i,v in enumerate(payload): buf[i]=v
        result=self.lib.libusb_control_transfer(self.handle,bm,request,value,index,
                                                buf,length,3000)
        if result<0:
            return {"status":"stall_or_transport_error","libusb_code":result,
                    "data_hex":""}
        return {"status":"ok","libusb_code":result,
                "data_hex":bytes(buf[:result]).hex()}

    def feature(self, request, length=2):
        return self.transfer(0xA1,request,0x0800,0x0200,length)

    def set_feature(self, value):
        return self.transfer(0x21,1,0x0800,0x0200,2,value.to_bytes(2,'little'))

    def descriptor(self, kind, length):
        return self.transfer(0x80,6,kind<<8,0,length)

    def close(self):
        if getattr(self,'handle',None):
            self.lib.libusb_close(self.handle); self.handle=None
        if getattr(self,'ctx',None):
            self.lib.libusb_exit(self.ctx); self.ctx=None


def sha(data): return hashlib.sha256(data).hexdigest()


def write_ram(device, address, data):
    for i,value in enumerate(data): device.exchange(0xB6,address+i,value)


def capture_mode(size):
    rate='5' if size=='1920x1080' else '10'
    output=subprocess.run(["ffmpeg","-nostdin","-hide_banner","-loglevel","error",
        "-f","avfoundation","-framerate",rate,"-video_size",size,
        "-pixel_format","yuyv422","-i","usb video:none","-frames:v","2",
        "-f","null","-"],capture_output=True,text=True,timeout=30)
    if output.returncode:
        raise RuntimeError(f"{size} capture failed: {output.stderr[-1200:]}")
    return {"size":size,"rate":rate,"frames_requested":2,"returncode":output.returncode}


def run(output):
    candidate=(ART/"ms2109-sharpness-candidate.bin").read_bytes()
    if sha(candidate)!=EXPECTED_CANDIDATE or validate(candidate)!=OVERLAY_LENGTH:
        raise RuntimeError("Candidate hash or EEPROM checksum validation failed")
    if output.exists(): raise RuntimeError(f"Refusing to overwrite {output}")
    output.parent.mkdir(parents=True,exist_ok=True)
    device=Device()
    uvc=None
    result={"scope":"volatile RAM qualification; no EEPROM writes",
            "candidate_sha256":sha(candidate),"before":{},"checks":{},
            "restoration":{"attempted":False}}
    snapshots={}
    touched=False
    try:
        print("Verifying live EEPROM and saving volatile state…",flush=True)
        if device.identify_eeprom()!=2048: raise RuntimeError("Expected 2 KiB EEPROM")
        live_eeprom=device.read('eeprom',0,2048)
        result['live_eeprom_sha256_before']=sha(live_eeprom)
        if sha(live_eeprom)!=EXPECTED_EEPROM:
            raise RuntimeError("Live EEPROM differs from the approved rollback image")
        if live_eeprom!=(ART/"live-prequal-eeprom.bin").read_bytes():
            raise RuntimeError("Live EEPROM differs from the verified two-read backup")
        # Snapshot the entire candidate image extent, response-copy buffer,
        # descriptor regions touched by retained callbacks, and current controls.
        ranges=[(0xCBD0,0x7FE),(DESC_START,DESC_LENGTH),(0xC0BF,0x1FA),
                (0xC2A4,6),(0xC43B,6),(0xC6A0,8),(0xC4C5,1),(0xC4C9,3),
                (0xFE60,1),(0xFE84,2),(0xFE90,4),(0xDE08,4)]
        for address,length in ranges:
            snapshots[address]=device.read('ram',address,length)
        result['before']={f'{a:04X}':v.hex() for a,v in snapshots.items()}
        result['loaded_image_matches_eeprom']=(
            snapshots[0xCBD0][48:48+int.from_bytes(live_eeprom[2:4],'big')+4]
            ==live_eeprom[48:48+int.from_bytes(live_eeprom[2:4],'big')+4])
        if not result['loaded_image_matches_eeprom']:
            raise RuntimeError("Loaded overlay does not match the verified EEPROM image")
        result['candidate_overlay_sha256']=sha(candidate[48:48+OVERLAY_LENGTH])
        result['previous_flags']=snapshots[0xCBD0][4]
        # Disable only the three callback gates whose entries or callers are
        # replaced. Keep other original callback bits exactly as they were.
        masked=bytes((result['previous_flags'] & ~0x07,))
        device.exchange(0xB6,0xCBD4,masked[0]); time.sleep(.03); touched=True
        if device.read('ram',0xCBD4,1)!=masked:
            raise RuntimeError("Could not quiesce callback gates")
        print("Callbacks quiesced; staging candidate in RAM…",flush=True)
        # Publish the new header and body with hooks still disabled. Flags are
        # enabled only after the complete loaded-image readback succeeds.
        header=bytearray(candidate[:48]); header[4]=masked[0]
        write_ram(device,0xCBD0,bytes(header))
        write_ram(device,OVERLAY_START,candidate[48:48+OVERLAY_LENGTH+4])
        if device.read('ram',0xCBD0,48)!=bytes(header):
            raise RuntimeError("Candidate header readback failed")
        if device.read('ram',OVERLAY_START,OVERLAY_LENGTH+4)!=candidate[48:48+OVERLAY_LENGTH+4]:
            raise RuntimeError("Candidate overlay/checksum readback failed")
        # Start at the agreed default. The selection byte is in CC1A.
        device.exchange(0xB6,0xCC1A,64)
        device.exchange(0xB6,0xFE84,64)
        device.exchange(0xB6,0xFE85,0)
        flags=candidate[4]
        device.exchange(0xB6,0xCBD4,flags); time.sleep(.05)
        if device.read('ram',0xCBD4,1)!=bytes((flags,)):
            raise RuntimeError("Candidate callback gates did not enable")
        result['candidate_live']=True
        print("Candidate is active in volatile RAM; querying UVC controls…",flush=True)
        uvc=UVC()
        # Active and other-speed configuration descriptor paths.
        # ROM 75CC's other-speed header declares 0x0163 (355) bytes; the
        # surrounding CODE window is longer because the next descriptor follows.
        for kind,length in ((2,1211),(7,355)):
            desc=uvc.descriptor(kind,length)
            raw=bytes.fromhex(desc['data_hex'])
            if desc['status']!='ok' or len(raw)!=length:
                raise RuntimeError(f"Configuration descriptor type {kind} failed: {desc}")
            result['checks'][f'descriptor_type_{kind}']={"bytes":len(raw),
                "header_hex":raw[0x39:0x43].hex(),
                "processing_unit_controls":raw[0x41:0x43].hex(),
                "sharpness_bit":bool(raw[0x41]&0x10),
                "candidate_scratch_controls":device.read('ram',DESC_START+0x41,2).hex()}
            if raw[0x41]&0x10==0:
                result['checks'].setdefault('descriptor_warnings',[]).append(
                    f"type {kind}: controls {raw[0x41:0x43].hex()} at offset 0x41")
        expected={0x81:2,0x82:2,0x83:2,0x84:2,0x85:2,0x86:1,0x87:2}
        for req,length in expected.items():
            got=uvc.feature(req,length)
            if got['status']!='ok' or len(bytes.fromhex(got['data_hex']))!=length:
                raise RuntimeError(f"Sharpness GET request {req:02X} failed: {got}")
            result['checks'][f'GET_{req:02X}']=got['data_hex']
        if result['checks']['GET_82']!='0000' or result['checks']['GET_83']!='7f00' or \
           result['checks']['GET_84']!='0100' or result['checks']['GET_85']!='0200' or \
           result['checks']['GET_86']!='03' or result['checks']['GET_87']!='4000':
            raise RuntimeError("Sharpness query values differ from the agreed UVC contract")
        for value in (0,64,127):
            sent=uvc.set_feature(value)
            time.sleep(.02)
            current=uvc.feature(0x81,2)
            fe84=device.read('ram',0xFE84,1)[0]
            fe85=device.read('ram',0xFE85,1)[0]
            if sent['status']!='ok' or current['data_hex']!=value.to_bytes(2,'little').hex() or \
               fe84!=value or fe85!=0:
                raise RuntimeError(f"SET_CUR {value} failed: set={sent}, cur={current}, FE84={fe84:02X}, FE85={fe85:02X}")
            result['checks'][f'SET_{value}']={"status":"ok","GET_CUR":current['data_hex'],
                "FE84":fe84,"FE85":fe85}
        invalid=uvc.set_feature(128)
        after_invalid=uvc.feature(0x81,2)
        if invalid['status']=='ok' or after_invalid['data_hex']!='7f00' or \
           device.read('ram',0xFE84,1)!=b'\x7f':
            raise RuntimeError(f"Out-of-range SET_CUR was not rejected without changing state: {invalid}")
        result['checks']['SET_128']={"status":invalid['status'],"GET_CUR_after":after_invalid['data_hex'],
                                    "FE84_after":127}
        # Unrelated Processing Unit brightness stays on the stock ROM path.
        result['checks']['brightness_GET_CUR']=uvc.transfer(0xA1,0x81,0x0200,0x0200,2)
        if result['checks']['brightness_GET_CUR']['status']!='ok':
            raise RuntimeError("Unrelated brightness request did not delegate to stock ROM")
        captures=[]
        for size in ('1920x1080','1280x720'):
            print(f"Capturing {size} stream restart…",flush=True)
            captures.append(capture_mode(size))
            cur=uvc.feature(0x81,2)
            if cur['data_hex']!='7f00' or device.read('ram',0xFE84,1)!=b'\x7f':
                raise RuntimeError(f"Sharpness did not survive {size} capture restart: {cur}")
        result['checks']['stream_restarts']=captures
        result['checks']['SET_CUR_max_after_streams']=uvc.feature(0x81,2)['data_hex']
        uvc.close(); uvc=None
        descriptor_ok=all(result['checks'][f'descriptor_type_{kind}']['sharpness_bit']
                          for kind in (2,7))
        result['status']=('passed; candidate executed in volatile RAM only' if descriptor_ok
                          else 'partial: UVC controls exercised; descriptor capability bit mismatch')
    finally:
        print("Restoring original RAM snapshot and checking EEPROM…",flush=True)
        if uvc is not None: uvc.close()
        if touched:
            result['restoration']['attempted']=True
            try:
                # Mask candidate callback gates before restoring code/state.
                device.exchange(0xB6,0xCBD4,result['previous_flags'] & ~0x07)
                time.sleep(.03)
                for address,data in snapshots.items():
                    if address==0xCBD0:
                        header=bytearray(data); header[4]=result['previous_flags'] & ~0x07
                        write_ram(device,address,bytes(header))
                    else:
                        write_ram(device,address,data)
                device.exchange(0xB6,0xCBD4,result['previous_flags'])
                result['restoration']['ram_ranges_match']=all(
                    device.read('ram',address,len(data))==data for address,data in snapshots.items())
                result['restoration']['flags']=device.read('ram',0xCBD4,1).hex()
                eeprom1=device.read('eeprom',0,2048); eeprom2=device.read('eeprom',0,2048)
                result['restoration']['eeprom_sha256_read1']=sha(eeprom1)
                result['restoration']['eeprom_sha256_read2']=sha(eeprom2)
                result['restoration']['eeprom_unchanged']=(eeprom1==eeprom2 and sha(eeprom1)==EXPECTED_EEPROM)
                if not result['restoration']['ram_ranges_match'] or not result['restoration']['eeprom_unchanged']:
                    result['status']='FAILED: restoration verification failed; power-cycle to reload EEPROM'
            except BaseException as error:
                result['restoration']['error']=repr(error)
                result['status']='FAILED: RAM restoration needs attention; power-cycle to reload EEPROM'
        if 'status' not in result:
            result['status']='FAILED: qualification stopped before all checks completed'
        device.close()
        output.write_text(json.dumps(result,indent=2)+'\n')
        if result.get('status','').startswith('FAILED'):
            raise RuntimeError(result['status'])
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    run(args.output)
