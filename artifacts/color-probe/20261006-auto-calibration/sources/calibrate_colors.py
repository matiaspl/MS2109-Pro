#!/usr/bin/env python3
"""Measured MS2109 range calibration; writes results and restores controls.

run: one native macOS administrator prompt, temporary B/C/S sweeps, raw USB
YUY2 and JPEG YCbCr, no firmware writes. analyze: file-only replay of a run.
Dependencies: clang, libuvc, libjpeg-turbo, NumPy, Pillow (Homebrew paths).
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone

import numpy as np
from PIL import Image
from probe_colors import ROOT, matrix, rmse, unpack, write_json

GROUPS = ["gray", "red", "green", "blue", "cyan", "magenta", "yellow"]


def chart():
    patches = []
    masks = [[1,1,1], [1,0,0], [0,1,0], [0,0,1], [0,1,1], [1,0,1], [1,1,0]]
    for group, mask in zip(GROUPS, masks):
        for code in range(256):
            patches.append({"name": f"{group}-{code}", "group": group, "code": code,
                            "rgb": [code*c for c in mask]})
    rng = random.Random(2109)
    while len(patches) < 1920:
        patches.append({"name": f"mixed-{len(patches)-1792}", "group": "mixed",
                        "rgb": [rng.randrange(256) for _ in range(3)]})
    for i, patch in enumerate(patches):
        patch["rect"] = [i % 60*32, i // 60*32, 32, 32]
    return {"width": 1920, "height": 1080, "columns": 60, "rows": 32,
            "coverage": "256 codes on seven RGB ramps and 128 mixed colors; not all RGB triplets",
            "patches": patches}


def samples(image, patches):
    # 8x8 centers inside uniform, 32x32 JPEG-MCU-aligned tiles.
    return np.stack([image[p["rect"][1]+12:p["rect"][1]+20,
                          p["rect"][0]+12:p["rect"][0]+20].reshape(64, 3) for p in patches])


def jpeg_headers(payload):
    """Audit coding tables/scan references without adding or changing markers."""
    if not payload.startswith(b"\xff\xd8") or not payload.endswith(b"\xff\xd9"):
        raise ValueError("Missing JPEG SOI/EOI")
    i = 2; markers = []; qt = set(); ht = set(); components = {}; scan_ok = False
    while i < len(payload):
        if payload[i] != 255:
            raise ValueError("Unexpected JPEG marker boundary")
        while payload[i] == 255: i += 1
        code = payload[i]; i += 1
        if code == 0xd9: break
        length = int.from_bytes(payload[i:i+2], "big")
        if length < 2 or i+length > len(payload): raise ValueError("Bad JPEG segment length")
        data = payload[i+2:i+length]; i += length
        item = {"marker": f"FF{code:02X}", "length": length}
        if 0xe0 <= code <= 0xef: item["prefix_hex"] = data[:16].hex()
        markers.append(item)
        if code == 0xdb:
            j = 0
            while j < len(data):
                precision = data[j] >> 4; qt.add(data[j] & 15)
                if precision > 1: raise ValueError("Bad DQT precision")
                j += 1+64*(precision+1)
            if j != len(data): raise ValueError("Truncated DQT")
        if code == 0xc4:
            j = 0
            while j < len(data):
                if j+17 > len(data): raise ValueError("Truncated DHT")
                ht.add((data[j] >> 4, data[j] & 15))
                j += 17+sum(data[j+1:j+17])
            if j != len(data): raise ValueError("Bad DHT length")
        if code == 0xc0:
            if len(data) != 6+3*data[5]: raise ValueError("Bad SOF0")
            components = {data[j]: data[j+2] for j in range(6, len(data), 3)}
            item["dimensions"] = [int.from_bytes(data[3:5], "big"), int.from_bytes(data[1:3], "big")]
        if code == 0xda:
            if len(data) != 1+2*data[0]+3: raise ValueError("Bad SOS")
            scan_ok = bool(components)
            for j in range(1, 1+2*data[0], 2):
                component, table = data[j:j+2]
                scan_ok &= component in components and components[component] in qt
                scan_ok &= (0, table >> 4) in ht and (1, table & 15) in ht
            break  # Entropy bytes are validated by libjpeg, not this header audit.
    return {"markers_before_scan": markers, "quantization_table_ids": sorted(qt),
            "huffman_tables": sorted([list(t) for t in ht]),
            "referenced_coding_tables_present": bool(scan_ok),
            "JFIF": any(m["marker"] == "FFE0" and m.get("prefix_hex", "").startswith(b"JFIF\0".hex()) for m in markers),
            "Adobe": any(m["marker"] == "FFEE" and m.get("prefix_hex", "").startswith(b"Adobe".hex()) for m in markers)}


def targets(rgb, chroma):
    m, off = matrix("709", "full")
    full = rgb @ m.T+off
    if chroma == "preserve":
        ml, ol = matrix("709", "limited")
        full[:, 1:] = (rgb @ ml.T+ol)[:, 1:]
    return np.clip(full, 0, 255)


def metrics(values, pixels, rgb, chroma):
    ideal = targets(rgb, chroma); gray = values[:256, 0]
    delta = np.diff(gray); first, last = float(gray[0]), float(gray[-1])
    endpoint_gap = abs(first)+abs(255-last)
    false_clip = ((values <= .5) & (ideal > 1.5)) | ((values >= 254.5) & (ideal < 253.5))
    gray_false = int(np.sum(false_clip[:256, 0]))
    endpoint_plateau = int(np.sum(gray[1:] == first)+np.sum(gray[:-1] == last))
    per_channel = np.sqrt(np.mean((ideal-values)**2, axis=0))
    gray_error = rmse(ideal[:256, 0], gray)
    minima = values.min(axis=0); maxima = values.max(axis=0)
    chroma_gap = float(np.sum(minima[1:]+255-maxima[1:])) if chroma == "full" else 0.
    # Explicit loss: endpoint coverage, numeric fidelity and early clipping.
    # Score the worst transport; large contrast that collapses ramps cannot win.
    loss = (gray_error+per_channel[0]+endpoint_gap*.5+gray_false*3
            + max(0, endpoint_plateau-2)*1.5+int(np.sum(delta < 0))*100)
    if chroma == "full":
        loss += float(per_channel[1:].mean())*2+chroma_gap*.25+float(false_clip[:, 1:].sum())*.25
    return {"score_loss": float(loss), "gray_black_white": [first, last],
            "gray_span": last-first, "gray_unique_patch_median_levels": len(np.unique(gray)),
            "gray_unique_rounded_patch_median_codes": len(np.unique(np.rint(gray))),
            "gray_unique_pixel_distribution_signatures": len({p.tobytes() for p in np.sort(pixels[:256,:,0], axis=1)}),
            "gray_collapsed_adjacent_steps": int(np.sum(delta == 0)),
            "gray_nonmonotonic_steps": int(np.sum(delta < 0)),
            "gray_false_clipped_input_levels": gray_false,
            "gray_endpoint_plateau_extra_inputs": endpoint_plateau,
            "gray_target_rmse": gray_error, "target_rmse_per_channel": per_channel.tolist(),
            "target_false_clipped_patch_components": false_clip.sum(axis=0).tolist(),
            "measured_median_ranges": np.stack([minima,maxima],axis=1).tolist(),
            "raw_sample_pixel_ranges": np.stack([pixels.min(axis=(0,1)),pixels.max(axis=(0,1))],axis=1).tolist()}


def compile_tools(directory):
    frameworks = ["Cocoa", "AVFoundation", "CoreMedia", "CoreVideo", "CoreGraphics", "ImageIO", "UniformTypeIdentifiers", "ScreenCaptureKit"]
    commands = {
        "server": ["clang", "-Wall", "-Wextra", "-O2", "-I/opt/homebrew/include", "-L/opt/homebrew/lib", str(ROOT/"tools/calibrate_uvc_server.c"), "-luvc", "-o", str(directory/"server")],
        "admin": ["clang", "-fobjc-arc", "-framework", "Foundation", "-framework", "Security", str(ROOT/"tools/run_capture_video_uvc_admin.m"), "-o", str(directory/"admin")],
        "display": ["clang", "-fobjc-arc", "-Wno-deprecated-declarations", *[v for f in frameworks for v in ["-framework", f]], str(ROOT/"tools/color_probe_macos.m"), "-o", str(directory/"display")],
        "decode": ["clang", "-I/opt/homebrew/include", "-L/opt/homebrew/lib", str(ROOT/"tools/decode_jpeg_ycbcr.c"), "-ljpeg", "-o", str(directory/"decode")],
    }
    for command in commands.values(): subprocess.run(command, check=True)
    return {name: directory/name for name in commands}


def analyze_sample(run, id, decoder, tmp):
    source = json.loads((run/"usb-source/display-ready.json").read_text())
    patches = source["patch_reference"]; rgb = np.array([p["expected_display_rgb"] for p in patches], float)
    if [(p["rgb"],p["rect"]) for p in patches] != [(p["rgb"],p["rect"]) for p in chart()["patches"]]:
        raise ValueError("Chart/reference mismatch")
    image = np.array(Image.open(run/"usb-source/source-render.png").convert("RGB"))
    source_error = rmse(np.median(samples(image,patches),axis=1),rgb)
    if source_error > .5: raise ValueError("Source render/reference mismatch")
    response = json.loads((run/f"usb/response-{id:03d}.json").read_text())
    if response["exit_code"] or not response["controls_restoration_ok"]: raise ValueError("Sample or restoration failed")
    result = {"id": id, "controls": response["controls_active"], "source_rgb_rmse": source_error, "formats": {}}
    for mode in ["yuy2", "mjpeg"]:
        base = run/f"usb/captures/sample-{id:03d}"/mode
        meta = json.loads((base/"usb-capture.json").read_text())
        if meta["exit_code"] or len(meta["frames"]) != 3 or meta["controls_active"] != result["controls"]:
            raise ValueError("Incomplete recording or wrong controls")
        per_frame = []; pixel_frames = []; header = None; details = None
        for frame in meta["frames"]:
            path = base/frame["file"]
            if path.stat().st_size != frame["bytes"]: raise ValueError("Payload length mismatch")
            if mode == "mjpeg":
                payload = path.read_bytes(); audit = jpeg_headers(payload)
                if not audit["referenced_coding_tables_present"]: raise ValueError("Missing JPEG coding tables")
                output, info = tmp/"frame.ycbcr", tmp/"frame.json"
                subprocess.run([str(decoder), str(path), str(output), str(info)], check=True, capture_output=True)
                details = json.loads(info.read_text())
                if details["warnings"]: raise ValueError("JPEG decoder warning")
                image = np.fromfile(output,np.uint8).reshape(1080,1920,3);output.unlink();info.unlink();header=audit
            else: image = unpack(path,frame)
            pixels = samples(image,patches);per_frame.append(np.median(pixels,axis=1));pixel_frames.append(pixels)
        values = np.median(per_frame,axis=0); pixels = np.concatenate(pixel_frames,axis=1)
        if np.ptp(per_frame,axis=0).max()>2: raise ValueError("Unstable captured chart; refusing to score candidate")
        if values[255,0]-values[0,0] < 100 or np.corrcoef(np.arange(256),values[:256,0])[0,1] < .97:
            raise ValueError("Captured content is not the calibration chart")
        format_result = {"preserve": metrics(values,pixels,rgb,"preserve"), "full": metrics(values,pixels,rgb,"full"),
                         "maximum_temporal_patch_span": float(np.ptp(per_frame,axis=0).max()),
                         "median_values": values.tolist(), "mean_values": pixels.mean(axis=1).tolist(),
                         "jpeg_header_audit": header, "jpeg_decoder": details}
        result["formats"][mode] = format_result
        with (base/"patches.csv").open("w",newline="") as f:
            w = csv.writer(f);w.writerow(["name","R","G","B","median_Y","median_Cb","median_Cr","mean_Y","mean_Cb","mean_Cr"])
            for p,r,v,mean in zip(patches,rgb,values,pixels.mean(axis=1)): w.writerow([p["name"],*r,*v,*mean])
    result["transport_median_yuv_rmse"] = rmse(np.array(result["formats"]["yuy2"]["median_values"]),np.array(result["formats"]["mjpeg"]["median_values"]))
    result["loss_preserve"] = max(f["preserve"]["score_loss"] for f in result["formats"].values())
    result["loss_full"] = max(f["full"]["score_loss"] for f in result["formats"].values())
    write_json(run/f"sample-{id:03d}.json",result)
    return result


def predict(baseline, shifted, contrast):
    def fit(sample):
        y = np.array(sample["formats"]["yuy2"]["median_values"])[:256,0]
        return np.linalg.lstsq(np.c_[np.arange(256),np.ones(256)],y,rcond=None)[0]
    a,o = fit(baseline); ab,ob = fit(shifted); ac,oc = fit(contrast)
    b0,c0 = baseline["controls"]["brightness_ui"],baseline["controls"]["contrast"]
    db = shifted["controls"]["brightness_ui"]-b0; dc = contrast["controls"]["contrast"]-c0
    brightness_gain = (ob-o)/db; slope_per_contrast = (ac-a)/dc
    if not (.5 < brightness_gain < 2 and slope_per_contrast > .001): raise ValueError("Control response cannot be modeled safely")
    target_c = c0+(1-a)/slope_per_contrast
    target_b = b0-(o+(oc-o)/dc*(target_c-c0))/brightness_gain
    return {"predicted_brightness_ui": float(target_b), "predicted_contrast": float(target_c),
            "brightness_y_codes_per_step": float(brightness_gain), "y_slope_per_contrast_step": float(slope_per_contrast),
            "baseline_y_slope": float(a), "baseline_y_offset": float(o),
            "brightness_changes_slope": float(ab-a), "model": "local affine gray-ramp response; candidates still measured"}


def finalize(run, records, prediction=None):
    original = json.loads((run/"usb/ready.json").read_text())["original"]
    preserve = min((r for r in records if r["controls"]["saturation"] == original["saturation"]),key=lambda r:r["loss_preserve"])
    full = min(records,key=lambda r:r["loss_full"])
    def compact(r,target):
        return {"sample_id":r["id"],"controls":r["controls"],"score_loss":r[f"loss_{target}"],
                "formats":{name:{**f[target],"maximum_temporal_patch_span":f["maximum_temporal_patch_span"]} for name,f in r["formats"].items()},
                "transport_median_yuv_rmse":r["transport_median_yuv_rmse"]}
    rgb = np.array([p["expected_display_rgb"] for p in json.loads((run/"usb-source/display-ready.json").read_text())["patch_reference"]],float)
    baseline_values = np.array(records[0]["formats"]["yuy2"]["median_values"])
    models = []
    for name in ["601","709","2020"]:
        for rng in ["limited","full"]:
            m,o = matrix(name,rng);models.append({"matrix":name,"range":rng,"rmse":rmse(rgb@m.T+o,baseline_values)})
    result = {"utc":datetime.now(timezone.utc).isoformat(), "original_controls":original,
              "measured_candidates":len(records), "best_luma_with_original_saturation":compact(preserve,"preserve"),
              "best_full_ycbcr":compact(full,"full"), "local_prediction":prediction,
              "baseline_models":sorted(models,key=lambda m:m["rmse"]),
              "restoration":json.loads((run/"usb/session.json").read_text()),
              "jpeg_header_audit":records[0]["formats"]["mjpeg"]["jpeg_header_audit"],
              "metadata_recommendations":{
                  "matrix": "BT.709 (UVC matrix value 1) if baseline numeric model still verifies 709",
                  "primaries_and_transfer": "Not independently identified by this numeric chart. Preserve declarations until independently measured.",
                  "quantization": "Signal measured range in the consumer/container; UVC color descriptor has no range field.",
                  "jpeg": "Coding-table audit is separate from color signaling. JFIF cannot declare BT.709 matrix. Adding an APP marker cannot recover clipped samples or fix a decoder assuming BT.601."},
              "limitations":["Best among measured candidates in a local search; not all 256 cubed control settings.",
                             "RGB reference is the AppKit source render before compositor/HDMI; HDMI wire codes and physical primaries/OETF are not measured.",
                             "Seven 256-code ramps plus 128 mixed patches; not all 16.7 million RGB triplets.",
                             "Stretching a quantized signal cannot restore lost input precision.",
                             "Original USB samples only; AVFoundation's MJPEG decode/range conversion is a separate path."]}
    write_json(run/"result.json",result)
    with (run/"candidates.csv").open("w",newline="") as f:
        w=csv.writer(f);w.writerow(["sample","brightness_ui","brightness_signed","contrast","saturation","preserve_loss","full_loss","YUY2_black","YUY2_white","YUY2_gray_unique","MJPEG_black","MJPEG_white","MJPEG_gray_unique"])
        for r in records:
            w.writerow([r["id"],*[r["controls"][k] for k in ["brightness_ui","brightness_signed","contrast","saturation"]],r["loss_preserve"],r["loss_full"],*[v for mode in ["yuy2","mjpeg"] for v in [*r["formats"][mode]["full"]["gray_black_white"],r["formats"][mode]["full"]["gray_unique_patch_median_levels"]]]])
    lines=["# MS2109 automatic range calibration", "",f"Measured {len(records)} settings; original controls restored: **{result['restoration']['controls_restoration_ok']}**.","",
           "The search scores coverage, BT.709 numeric fidelity, early clipping and collapsed endpoint steps. Both original USB transports are measured; the worse transport sets the loss.",""]
    for title,key in [("Luma with original saturation","best_luma_with_original_saturation"),("Full YCbCr target","best_full_ycbcr")]:
        selected=result[key];c=selected["controls"]
        lines += [f"## {title}","",f"Brightness UI **{c['brightness_ui']}** (signed UVC {c['brightness_signed']}), contrast **{c['contrast']}**, saturation **{c['saturation']}**, hue {c['hue']}.","",
                  "| Transport | Gray Y | Cb | Cr | Gray median levels | Early clipped gray inputs | Target Y/Cb/Cr RMSE |","|---|---|---|---|---:|---:|---|"]
        for mode,f in selected["formats"].items():
            ranges=[f"{v[0]:g}…{v[1]:g}" for v in f["measured_median_ranges"]]
            lines.append(f"| {mode} | {' | '.join(ranges)} | {f['gray_unique_patch_median_levels']} | {f['gray_false_clipped_input_levels']} | {' / '.join(f'{v:.3f}' for v in f['target_rmse_per_channel'])} |")
        lines.append("")
    lines += ["## Color declarations and JPEG headers","", "The original JPEG frames contain the quantization and Huffman tables referenced by their scan. The tool reports marker inventories without modifying frames.","",
              "The baseline matrix/range model is measured numerically. Physical primaries and transfer are not identified by this test. JFIF's color model does not provide a BT.709 matrix declaration ([ITU-T T.871](https://www.itu.int/rec/T-REC-T.871-201105-I/en)). FFmpeg's MJPEG decoder starts with BT.601-family color assumptions ([source](https://raw.githubusercontent.com/FFmpeg/FFmpeg/master/libavcodec/mjpegdec.c)). Consumer range/matrix handling must be tested independently of firmware descriptor edits.","",
              "## Validation boundaries","", *[f"- {s}" for s in result["limitations"]],"", "No firmware writes; recommended controls were not left applied. Raw frames, readbacks, source chart/profile, source snapshots and SHA-256 hashes accompany this result."]
    (run/"report.md").write_text("\n".join(lines)+"\n")
    return result


class Client:
    def __init__(self,run,process): self.run=run;self.process=process;self.done=threading.Event();self.thread=threading.Thread(target=self.heartbeat,daemon=True);self.thread.start()
    def heartbeat(self):
        while not self.done.is_set():
            if (self.run/"usb").is_dir(): (self.run/"usb/heartbeat").touch()
            self.done.wait(2)
    def wait(self,path,timeout):
        deadline=time.monotonic()+timeout
        while not path.exists():
            if self.process.poll() is not None: raise RuntimeError(f"Capture helper exited {self.process.returncode}; see capture.log")
            if time.monotonic()>deadline: raise TimeoutError(f"Waiting for {path.name}")
            time.sleep(.2)
        return json.loads(path.read_text())
    def request(self,text):
        path=self.run/"usb/request.txt"
        if path.exists(): raise RuntimeError("Previous request pending")
        tmp=path.with_suffix(".tmp");tmp.write_text(text);tmp.replace(path)
    def stop(self):
        if self.process.poll() is None and (self.run/"usb/ready.json").exists():
            # Do not interrupt an in-flight capture: its own timeout restores controls.
            deadline=time.monotonic()+30
            while (self.run/"usb/request.txt").exists() and time.monotonic()<deadline: time.sleep(.2)
            if not (self.run/"usb/request.txt").exists(): self.request("stop\n")
        self.done.set();self.thread.join(3)
        try: self.process.wait(timeout=55)
        except subprocess.TimeoutExpired: raise RuntimeError("Privileged helper has not finished; inspect session restoration before proceeding")


def run(args):
    run=args.output.resolve();run.mkdir(parents=True,exist_ok=False)
    write_json(run/"pattern.json",chart());records=[];prediction=None
    sources=run/"sources";sources.mkdir()
    for name in ["calibrate_colors.py","calibrate_uvc_server.c","run_capture_video_uvc_admin.m","color_probe_macos.m","decode_jpeg_ycbcr.c","probe_colors.py"]: shutil.copy2(ROOT/"tools"/name,sources/name)
    with tempfile.TemporaryDirectory(prefix="ms2109-calibration-") as td:
        td=Path(td);os.chmod(td,0o700);binaries=compile_tools(td)
        write_json(run/"binary-sha256.json",{k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in binaries.items()})
        inventory=subprocess.run([str(binaries["display"]),"list"],capture_output=True,text=True,check=True);(run/"inventory-before.json").write_text(inventory.stdout)
        with (run/"capture.log").open("w") as log:
            process=subprocess.Popen([str(binaries["admin"]),str(binaries["server"]),str(binaries["display"]),str(run/"pattern.json"),str(run/"usb"),"calibrate"],stdout=log,stderr=subprocess.STDOUT)
            client=Client(run,process)
            try:
                ready=client.wait(run/"usb/ready.json",300);o=ready["original"]
                cache={}
                def measure(b,c,s,label):
                    key=tuple(max(0,min(255,int(v))) for v in [b,c,s])
                    if key in cache:return cache[key]
                    id=len(records);print(f"Measure {id:02d}: B{key[0]} C{key[1]} S{key[2]} ({label})",flush=True)
                    client.request(f"{id} {key[0]} {key[1]} {key[2]}\n");client.wait(run/f"usb/response-{id:03d}.json",65)
                    r=analyze_sample(run,id,binaries["decode"],td);r["search_stage"]=label;records.append(r);cache[key]=r
                    write_json(run/f"sample-{id:03d}.json",r)
                    print(f"  Y {r['formats']['yuy2']['full']['gray_black_white']} / JPEG {r['formats']['mjpeg']['full']['gray_black_white']}, losses {r['loss_preserve']:.3f} / {r['loss_full']:.3f}",flush=True)
                    return r
                b,c,s=o["brightness_ui"],o["contrast"],o["saturation"]
                if b<16 or c>220 or c<32: raise ValueError("Starting controls are outside the bounded local calibration domain")
                baseline=measure(b,c,s,"baseline")
                rgb=np.array([p["expected_display_rgb"] for p in json.loads((run/"usb-source/display-ready.json").read_text())["patch_reference"]],float)
                bm,bo=matrix("709","limited")
                if rmse(rgb@bm.T+bo,np.array(baseline["formats"]["yuy2"]["median_values"]))>4:
                    raise ValueError("Baseline no longer matches BT.709 limited; do not infer a full-range expansion")
                shifted=measure(b-15,c,s,"brightness minus 15")
                increased=measure(b,c+8,s,"contrast response")
                prediction=predict(baseline,shifted,increased);write_json(run/"prediction.json",prediction)
                pb=round(prediction["predicted_brightness_ui"]);pc=round(prediction["predicted_contrast"])
                if not (32<=pc<=220 and 16<=pb<=220): raise ValueError("Predicted optimum outside bounded local search")
                measure(pb,pc,s,"predicted luma optimum")
                for db in [-1,0,1]:
                    for dc in [-1,0,1]: measure(pb+db,pc+dc,s,"luma neighborhood")
                best=min(records,key=lambda r:r["loss_preserve"])
                if best["controls"]["brightness_ui"] in [pb-1,pb+1] or best["controls"]["contrast"] in [pc-1,pc+1]:
                    center=best["controls"]
                    for db,dc in [(-1,0),(1,0),(0,-1),(0,1)]: measure(center["brightness_ui"]+db,center["contrast"]+dc,s,"luma boundary refinement")
                best=min(records,key=lambda r:r["loss_preserve"]);bc=best["controls"]
                # Conservative expected chroma expansion from limited to full; measure each.
                ps=round(s*255/224)
                for sat in range(max(0,ps-3),min(255,ps+3)+1): measure(bc["brightness_ui"],bc["contrast"],sat,"chroma neighborhood")
                bestfull=min(records,key=lambda r:r["loss_full"]);fc=bestfull["controls"]
                for db,dc in [(-1,0),(1,0),(0,-1),(0,1)]: measure(fc["brightness_ui"]+db,fc["contrast"]+dc,fc["saturation"],"full-range luma refinement")
            finally:
                client.stop()
        if process.returncode: raise RuntimeError(f"Calibration helper exited {process.returncode}; see capture.log")
        inventory=subprocess.run([str(binaries["display"]),"list"],capture_output=True,text=True,check=True);(run/"inventory-after.json").write_text(inventory.stdout)
        # Fresh AVFoundation frames verify that the normal UVC driver is usable again.
        with (run/"driver-restored.log").open("w") as log:
            subprocess.run([str(binaries["display"]),"--manifest",str(run/"pattern.json"),"--output",str(run/"driver-restored"),"--render-space","native","--transport","yuv","--frames","3"],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=45)
        result=finalize(run,records,prediction)
        restored=json.loads((run/"driver-restored/capture.json").read_text())
        patches=json.loads((run/"usb-source/display-ready.json").read_text())["patch_reference"]
        normal=np.median([np.median(samples(unpack(run/"driver-restored"/f["file"],f),patches),axis=1) for f in restored["frames"]],axis=0)
        comparison=rmse(normal,np.array(records[0]["formats"]["yuy2"]["median_values"]))
        result["driver_restored_avfoundation_frames"]=len(restored["frames"]);result["driver_restored_vs_original_usb_baseline_rmse"]=comparison
        write_json(run/"result.json",result)
    write_json(run/"sha256.json",{str(p.relative_to(run)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(run.rglob("*")) if p.is_file() and p.name!="sha256.json"})
    print(json.dumps({"result":str(run/"result.json"),"luma":result["best_luma_with_original_saturation"]["controls"],"full":result["best_full_ycbcr"]["controls"],"restored":result["restoration"]["controls_restoration_ok"],"normal_driver_baseline_rmse":comparison},indent=2),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest="command",required=True)
    r=sub.add_parser("run");r.add_argument("--output",required=True,type=Path)
    a=sub.add_parser("analyze");a.add_argument("run",type=Path)
    args=p.parse_args()
    if args.command=="run":run(args)
    else:
        directory=args.run.resolve();records=[json.loads(p.read_text()) for p in sorted(directory.glob("sample-*.json"))]
        prediction=json.loads((directory/"prediction.json").read_text()) if (directory/"prediction.json").exists() else None
        print(json.dumps(finalize(directory,records,prediction),indent=2))


if __name__=="__main__":main()
