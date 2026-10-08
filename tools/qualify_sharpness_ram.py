"""Verify Sharpness removal using a reversible volatile control-repair overlay.

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
ART = ROOT / "artifacts/ms2109-repair/20261007"
EXPECTED_EEPROM = "b1f78dd4ac512fa195261b7619fc8cd50498adaf48e199a0eb607dd0641e1ce8"
EXPECTED_CANDIDATE = "bee6059bc398bda76348e4dfe7d3df76fbedd32ac8d5a0d79af97ab3ed382bab"
OVERLAY_START = 0xCC00
DESC_START, DESC_LENGTH = 0xD800, 1211
REVIEWED_RUNTIME_OVERRIDES = {
    # This installed Sharpness build keeps its selected value in CC1A, and
    # runtime disables its old D0D8 -> D27F repair hook. The replacement
    # profile removes that state/hook and restores the factory D27F entry.
    0xCC1A: (0x40, 0x7F, 0xFF),
    0xD0D8: (0x02, 0x00, 0x02),
    0xD0D9: (0xD2, 0x00, 0xD2),
}


def classify_runtime_overrides(saved_image, loaded_image, candidate):
    """Accept only the three reviewed runtime changes, and verify target bytes."""
    if len(saved_image) != len(loaded_image):
        raise RuntimeError("Saved and loaded overlay lengths differ")
    actual = {
        OVERLAY_START + i: (saved, loaded)
        for i, (saved, loaded) in enumerate(zip(saved_image, loaded_image))
        if saved != loaded
    }
    expected = {
        address: (saved, loaded)
        for address, (saved, loaded, _candidate) in REVIEWED_RUNTIME_OVERRIDES.items()
    }
    if actual != expected:
        details = ", ".join(f"{address:04X}" for address in actual) or "none"
        raise RuntimeError(f"Unreviewed loaded-overlay differences at {details}")
    for address, (_saved, _loaded, candidate_value) in REVIEWED_RUNTIME_OVERRIDES.items():
        candidate_offset = 48 + address - OVERLAY_START
        if candidate[candidate_offset] != candidate_value:
            raise RuntimeError(f"Candidate byte at {address:04X} changed from reviewed value")
    return [
        {"address": f"0x{address:04X}", "eeprom_byte": f"0x{saved:02X}",
         "loaded_ram_byte": f"0x{loaded:02X}",
         "candidate_byte": f"0x{candidate_value:02X}"}
        for address, (saved, loaded, candidate_value) in REVIEWED_RUNTIME_OVERRIDES.items()
    ]


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


def require_stall(result, label):
    # libusb error -9 is LIBUSB_ERROR_PIPE, the expected EP0 STALL result.
    if result.get('status')!='stall_or_transport_error' or result.get('libusb_code')!=-9:
        raise RuntimeError(f"{label} did not produce an EP0 STALL: {result}")


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


def run(output, *, candidate_path=None, expected_current_path=None,
        expected_candidate_sha256=EXPECTED_CANDIDATE):
    candidate_path = candidate_path or ART/"ms2109-control-repair-candidate.bin"
    expected_current_path = expected_current_path or ART/"current-eeprom-readback.bin"
    candidate=candidate_path.read_bytes()
    overlay_length=validate(candidate)
    expected_eeprom=expected_current_path.read_bytes()
    expected_eeprom_sha256=sha(expected_eeprom)
    if sha(candidate)!=expected_candidate_sha256:
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
        if sha(live_eeprom)!=expected_eeprom_sha256:
            raise RuntimeError("Live EEPROM differs from the approved current image")
        if live_eeprom!=expected_eeprom:
            raise RuntimeError("Live EEPROM differs from the verified two-read backup")
        # Snapshot the entire candidate image extent, response-copy buffer,
        # descriptor regions touched by retained callbacks, and current controls.
        ranges=[(0xCBD0,0x7FE),(DESC_START,DESC_LENGTH),(0xC0BF,0x1FA),
                (0xC2A4,6),(0xC43B,6),(0xC6A0,8),(0xC4C5,1),(0xC4C9,3),
                (0xFE60,1),(0xFE84,2),(0xFE90,4),(0xDE08,4)]
        for address,length in ranges:
            snapshots[address]=device.read('ram',address,length)
        result['before']={f'{a:04X}':v.hex() for a,v in snapshots.items()}
        code_end=48+int.from_bytes(live_eeprom[2:4],'big')+4
        live_image=snapshots[0xCBD0][48:code_end]
        saved_image=live_eeprom[48:code_end]
        image_differences=[{'address':f"0x{0xCC00+i:04X}",
                            'eeprom_byte':f"0x{saved:02X}",
                            'loaded_ram_byte':f"0x{loaded:02X}"}
                           for i,(saved,loaded) in enumerate(zip(saved_image,live_image))
                           if saved!=loaded]
        result['loaded_image_diff']=image_differences
        result['loaded_image_matches_eeprom']=not image_differences
        if image_differences:
            result['reviewed_runtime_overrides']=classify_runtime_overrides(
                saved_image, live_image, candidate)
            repeated_snapshot=device.read('ram',0xCBD0,len(snapshots[0xCBD0]))
            if repeated_snapshot != snapshots[0xCBD0]:
                raise RuntimeError("Loaded RAM changed during preflight; refusing to stage candidate")
            result['loaded_ram_snapshot_repeated']=True
        result['candidate_overlay_sha256']=sha(candidate[48:48+overlay_length])
        result['previous_flags']=snapshots[0xCBD0][4]
        # Disable only the three callback gates whose entries or callers are
        # replaced. Keep other original callback bits exactly as they were.
        masked=bytes((result['previous_flags'] & ~0x07,))
        touched=True
        device.exchange(0xB6,0xCBD4,masked[0]); time.sleep(.03)
        if device.read('ram',0xCBD4,1)!=masked:
            raise RuntimeError("Could not quiesce callback gates")
        print("Callbacks quiesced; staging candidate in RAM…",flush=True)
        # Publish the new header and body with hooks still disabled. Flags are
        # enabled only after the complete loaded-image readback succeeds.
        header=bytearray(candidate[:48]); header[4]=masked[0]
        write_ram(device,0xCBD0,bytes(header))
        write_ram(device,OVERLAY_START,candidate[48:48+overlay_length+4])
        if device.read('ram',0xCBD0,48)!=bytes(header):
            raise RuntimeError("Candidate header readback failed")
        if device.read('ram',OVERLAY_START,overlay_length+4)!=candidate[48:48+overlay_length+4]:
            raise RuntimeError("Candidate overlay/checksum readback failed")
        flags=candidate[4]
        device.exchange(0xB6,0xCBD4,flags); time.sleep(.05)
        if device.read('ram',0xCBD4,1)!=bytes((flags,)):
            raise RuntimeError("Candidate callback gates did not enable")
        result['candidate_live']=True
        print("Candidate is active in volatile RAM; verifying Sharpness removal…",flush=True)
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
            offsets=(0x447,0x476,0x47F) if kind==2 else (0x0EF,0x11E,0x127)
            indexes=[raw[offset] for offset in offsets]
            result['checks'][f'descriptor_type_{kind}']['audio_interface_string_indexes']=indexes
            if raw[0x41]&0x10:
                raise RuntimeError(f"Configuration type {kind} still advertises Sharpness: {raw[0x41:0x43].hex()}")
        scaler_before=bytes(snapshots[0xFE84])
        result['checks']['sharpness_get_requests']={}
        for req,length in ((0x81,2),(0x82,2),(0x83,2),(0x84,2),
                           (0x85,2),(0x86,1),(0x87,2)):
            got=uvc.feature(req,length)
            require_stall(got,f"Retired Sharpness GET {req:02X}")
            result['checks']['sharpness_get_requests'][f'{req:02X}']=got
        sent=uvc.set_feature(64)
        require_stall(sent,'Retired Sharpness SET_CUR')
        result['checks']['sharpness_set_cur']=sent
        scaler_after=bytes(device.read('ram',0xFE84,2))
        if scaler_after!=scaler_before:
            raise RuntimeError(f"UVC Sharpness requests changed FE84/FE85: {scaler_before.hex()} -> {scaler_after.hex()}")
        result['checks']['FE84_FE85_unchanged']={"before":scaler_before.hex(),"after":scaler_after.hex()}
        # Unrelated Processing Unit brightness stays on the stock ROM path.
        result['checks']['brightness_GET_CUR']=uvc.transfer(0xA1,0x81,0x0200,0x0200,2)
        if result['checks']['brightness_GET_CUR']['status']!='ok':
            raise RuntimeError("Unrelated brightness request did not delegate to stock ROM")
        captures=[]
        for size in ('1920x1080','1280x720'):
            print(f"Capturing {size} stream restart…",flush=True)
            captures.append(capture_mode(size))
            scaler_now=bytes(device.read('ram',0xFE84,2))
            if scaler_now!=scaler_before:
                raise RuntimeError(f"Stream restart changed FE84/FE85: {scaler_before.hex()} -> {scaler_now.hex()}")
        result['checks']['stream_restarts']=captures
        uvc.close(); uvc=None
        descriptor_ok=all(not result['checks'][f'descriptor_type_{kind}']['sharpness_bit']
                          for kind in (2,7))
        result['status']=('passed; Sharpness hidden and selector requests rejected in volatile RAM only'
                          if descriptor_ok else 'failed: Sharpness remains advertised')
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
                if not result['restoration']['ram_ranges_match']:
                    result['status']='FAILED: restoration verification failed; power-cycle to reload EEPROM'
            except BaseException as error:
                result['restoration']['error']=repr(error)
                result['status']='FAILED: RAM restoration needs attention; power-cycle to reload EEPROM'
        try:
            eeprom1=device.read('eeprom',0,2048); eeprom2=device.read('eeprom',0,2048)
            result['postflight_eeprom_sha256_read1']=sha(eeprom1)
            result['postflight_eeprom_sha256_read2']=sha(eeprom2)
            result['postflight_eeprom_unchanged']=(
                eeprom1==eeprom2 and sha(eeprom1)==expected_eeprom_sha256)
            if not result['postflight_eeprom_unchanged']:
                result['status']='FAILED: EEPROM changed or readbacks disagree'
        except BaseException as error:
            result['postflight_eeprom_error']=repr(error)
            if result.get('status','').startswith('passed'):
                result['status']='FAILED: postflight EEPROM verification failed'
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
    parser.add_argument('--candidate',type=Path,default=ART/"ms2109-control-repair-candidate.bin")
    parser.add_argument('--expected-current',type=Path,default=ART/"current-eeprom-readback.bin")
    parser.add_argument('--expected-candidate-sha256',default=EXPECTED_CANDIDATE)
    args=parser.parse_args()
    run(args.output,candidate_path=args.candidate,
        expected_current_path=args.expected_current,
        expected_candidate_sha256=args.expected_candidate_sha256)
