#!/usr/bin/env python3
"""Display/capture an MS2109 color chart, then compare raw YUV matrix/range models.

Requires macOS/Xcode command-line tools, NumPy and Pillow. Acquisition must run
outside the macOS shell sandbox. The analyzer never opens a device.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import random
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
MATRICES = {"601": (0.299, 0.114), "709": (0.2126, 0.0722), "2020": (0.2627, 0.0593)}


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def pattern():
    patches = []
    def add(name, rgb):
        patches.append({"name": name, "rgb": rgb})
    for v in [0,1,2,4,8,12,16,20,24,28,32,40,48,56,64,80,96,112,128,144,160,176,192,208,224,232,235,240,248,252,254,255]:
        add(f"gray-{v}", [v]*3)
    for level in [255,192,128,64]:
        for name, rgb in [("red",[level,0,0]),("green",[0,level,0]),("blue",[0,0,level]),("cyan",[0,level,level]),("magenta",[level,0,level]),("yellow",[level,level,0])]:
            add(f"{name}-{level}",rgb)
    for name, rgb in [("skin-light",[194,150,130]),("skin-dark",[115,82,68]),("orange",[220,100,25]),("violet",[100,60,180]),("teal",[40,140,120]),("sky",[80,140,210]),("olive",[128,140,45]),("brown",[110,65,35])]:
        add(name,rgb)
    rng = random.Random(2109)
    while len(patches) < 96:
        add(f"mixed-{len(patches)}",[rng.randrange(24,232) for _ in range(3)])
    for i, p in enumerate(patches):
        p["rect"] = [i%12*160,i//12*135,160,135]
    return {"width":1920,"height":1080,"columns":12,"rows":8,"patches":patches}


def matrix(name, quantization):
    kr,kb=MATRICES[name];kg=1-kr-kb
    m=np.array([[kr,kg,kb],[-kr/(2*(1-kb)),-kg/(2*(1-kb)),.5],[.5,-kg/(2*(1-kr)),-kb/(2*(1-kr))]])
    if quantization=="limited":
        return np.array([219/255,224/255,224/255])[:,None]*m,np.array([16,128,128])
    return m,np.array([0,128,128])


def decode(yuv, name, quantization):
    m,offset=matrix(name,quantization)
    return (yuv-offset)@np.linalg.inv(m).T


def unpack(path, frame):
    w,h=frame["width"],frame["height"]
    a=np.fromfile(path,np.uint8)
    if a.size!=w*h*2 or w%2:
        raise ValueError(f"Invalid packed 422 frame length: {path}")
    a=a.reshape(h,w//2,4)
    y=np.empty((h,w),np.uint8)
    if frame["pixel_format"]=="2vuy":
        u,v=a[:,:,0],a[:,:,2];y[:,0::2]=a[:,:,1];y[:,1::2]=a[:,:,3]
    elif frame["pixel_format"]=="yuvs":
        u,v=a[:,:,1],a[:,:,3];y[:,0::2]=a[:,:,0];y[:,1::2]=a[:,:,2]
    else:
        raise ValueError("Unsupported pixel format; refusing to guess channel packing")
    return np.stack([y,np.repeat(u,2,1),np.repeat(v,2,1)],-1)


def patch_samples(image, patches):
    h,w=image.shape[:2]
    values=[];spread=[]
    for p in patches:
        x,y,pw,ph=p["rect"]
        # Central 40x40 pixels, far from chroma filtering, scaler and JPEG boundaries.
        cx,cy=round((x+pw/2)*w/1920),round((y+ph/2)*h/1080)
        roi=image[cy-20:cy+20,cx-20:cx+20].reshape(-1,3)
        values.append(np.median(roi,axis=0));spread.append(np.percentile(roi,95,axis=0)-np.percentile(roi,5,axis=0))
    return np.array(values),np.array(spread)


def rmse(a,b):
    return float(np.sqrt(np.mean((a-b)**2)))


def save_rgb(image, path):
    # Diagnostic previews use an explicit numeric YUV inverse. They do not apply
    # the AVFoundation "Composite NTSC" ICC profile or a display-profile inverse.
    Image.fromarray(np.rint(np.clip(image,0,255)).astype(np.uint8)).save(path)


def analyze_run(directory):
    directory=Path(directory)
    meta=json.loads((directory/"capture.json").read_text())
    frames=meta.get("frames",[])
    if len(frames)<3 or meta.get("error"):
        raise ValueError(f"Incomplete acquisition: {directory}")
    patches=meta["patch_reference"]
    rgb=np.array([p["expected_display_rgb"] for p in patches],float)
    per_frame=[];spreads=[];first=None
    for f in frames:
        image=unpack(directory/f["file"],f)
        if first is None:first=image
        values,spread=patch_samples(image,patches);per_frame.append(values);spreads.append(spread)
    samples=np.median(per_frame,axis=0)
    temporal=np.ptp(per_frame,axis=0)
    source=np.array(Image.open(directory/"source-render.png").convert("RGB"))
    source_values,_=patch_samples(source,patches)
    render_error=rmse(source_values,rgb)
    if render_error>2:
        raise ValueError(f"Source render disagrees with intended display RGB: RMSE={render_error:.2f}")
    # Ensure the captured image really contains the chart, not a desktop/stale frame.
    x=np.c_[rgb,np.ones(len(rgb))]
    train=np.arange(len(rgb))%2==0
    affine=np.linalg.lstsq(x[train],samples[train],rcond=None)[0]
    affine_pred=x@affine
    if rmse(affine_pred[~train],samples[~train])>12 or samples[31,0]-samples[0,0]<100:
        raise ValueError("Captured content does not validate as the displayed color chart")
    models=[]
    for name in MATRICES:
        for quantization in ["limited","full"]:
            m,offset=matrix(name,quantization)
            pred=rgb@m.T+offset
            # Constrained nuisance model: independent source RGB gains. An arbitrary
            # 3x3 fit cannot distinguish standard YUV matrices; never rank on that.
            a=np.einsum("ni,ci->nci",rgb[train],m).reshape(-1,3)
            gain=np.linalg.lstsq(a,(samples[train]-offset).ravel(),rcond=None)[0]
            adjusted=(rgb*gain)@m.T+offset
            inv=decode(samples,name,quantization)
            models.append({"matrix":name,"range":quantization,"direct_yuv_rmse":rmse(pred,samples),
                "direct_yuv_mae":float(np.mean(np.abs(pred-samples))),
                "rgb_rmse":rmse(inv,rgb),"gain_fit_rgb":gain.tolist(),
                "gain_fit_holdout_yuv_rmse":rmse(adjusted[~train],samples[~train]),
                "gain_fit_all_yuv_rmse":rmse(adjusted,samples)})
            save_rgb(decode(first,name,quantization),directory/f"capture-{name}-{quantization}.png")
    best=min(models,key=lambda m:m["direct_yuv_rmse"])
    gray_ids=[i for i,p in enumerate(patches) if p["name"].startswith("gray-")]
    gray=[]
    for i in gray_ids:
        gray.append({"source_code":patches[i]["rgb"][0],"display_rgb":rgb[i].tolist(),"yuv":samples[i].tolist()})
    summary={"run":directory.name,"utc_analyzed":datetime.now(timezone.utc).isoformat(),
        "macos_color_state":meta.get("macos_color_state"),"macos_color_state_end":meta.get("macos_color_state_end"),
        "render_space":meta["render_space"],"actual_active_subtype":meta["actual_active_subtype"],
        "actual_frame_duration":meta["actual_frame_duration"],"frame_count":len(frames),
        "delivered_pixel_format":frames[0]["pixel_format"],"size":[frames[0]["width"],frames[0]["height"]],
        "source_render_rgb_rmse":render_error,"maximum_patch_temporal_span":float(temporal.max()),
        "maximum_patch_spatial_p95_p05":float(np.max(spreads)),"models":models,
        "best_direct_model":best,"affine_rgb_to_yuv":affine.tolist(),
        "affine_holdout_yuv_rmse":rmse(affine_pred[~train],samples[~train]),
        "gray":gray,"patches":[{**p,"measured_yuv":samples[i].tolist(),"temporal_span":temporal[i].tolist()} for i,p in enumerate(patches)],
        "limitations":["RGB reference is the AppKit source render in the display ICC space, before late compositor/HDMI changes.",
            "AVFoundation may decode compressed transport before delivering YUV; actual active subtype is recorded.",
            "The on-wire HDMI RGB/YCbCr format and range were not independently measured.",
            "Smallest residual is a model fit, not proof of an isolated hardware matrix."]}
    write_json(directory/"analysis.json",summary)
    with (directory/"patches.csv").open("w",newline="") as f:
        writer=csv.writer(f);writer.writerow(["patch","intended_R","intended_G","intended_B","display_R","display_G","display_B","Y","Cb","Cr"])
        for i,p in enumerate(patches):writer.writerow([p["name"],*p["rgb"],*rgb[i],*samples[i]])
    return summary


def compare_transports(native, decoded, output):
    native=Path(native);decoded=Path(decoded)
    n=json.loads((native/"analysis.json").read_text());d=json.loads((decoded/"analysis.json").read_text())
    if n["render_space"]!=d["render_space"] or [(p["name"],p["rgb"],p["expected_display_rgb"]) for p in n["patches"]]!=[(p["name"],p["rgb"],p["expected_display_rgb"]) for p in d["patches"]]:
        raise ValueError("Comparison requires identical chart and source/display reference values")
    a=np.array([p["measured_yuv"] for p in n["patches"]]);b=np.array([p["measured_yuv"] for p in d["patches"]])
    scale=np.array([219/255,224/255,224/255]);offset=np.array([16,128,128])-np.array([0,128,128])*scale
    pred=a*scale+offset
    result={"native_directory":str(native.resolve()),"decoded_directory":str(decoded.resolve()),
        "identity_rmse":rmse(a,b),"full_to_limited_relative_scaling":scale.tolist(),"offset":offset.tolist(),
        "full_to_limited_rmse":rmse(pred,b),"per_channel_rmse":np.sqrt(np.mean((pred-b)**2,axis=0)).tolist(),
        "paired_patches":[]}
    for c,name in enumerate(["Y","Cb","Cr"]):
        result[name+"_fit"]=np.linalg.lstsq(np.c_[a[:,c],np.ones(len(a))],b[:,c],rcond=None)[0].tolist()
    for i in [0,31,32,33,34,35,36,37]:result["paired_patches"].append({"name":n["patches"][i]["name"],"native_yuv":a[i].tolist(),"decoded_yuv":b[i].tolist(),"predicted_relative_scaling":pred[i].tolist()})
    write_json(output,result)
    print("Identity RMSE:",round(result["identity_rmse"],4),"Extra full-to-limited RMSE:",round(result["full_to_limited_rmse"],4))


def montage(summaries, output):
    # Pillow composes measured source/capture evidence. It does not alter evidence frames.
    thumbs=[]
    font=ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf",20)
    for s in summaries:
        run=Path(output)/s["run"]
        for file,label in [("source-render.png","Source render"),("capture-601-limited.png","Captured: 601 limited"),("capture-709-limited.png","Captured: 709 limited")]:
            im=Image.open(run/file).convert("RGB");im=im.resize((640,360),Image.Resampling.NEAREST)
            tile=Image.new("RGB",(640,400),"#f2f2f2");tile.paste(im,(0,40));ImageDraw.Draw(tile).text((10,8),f"{s['run']}: {label}",fill="black",font=font);thumbs.append(tile)
    canvas=Image.new("RGB",(1920,400*len(summaries)),"white")
    for i,im in enumerate(thumbs):canvas.paste(im,(i%3*640,i//3*400))
    canvas.save(Path(output)/"comparison.png")


def analyze(directories, output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    summaries=[analyze_run(d) for d in directories]
    write_json(output/"analysis.json",summaries)
    # Only runs below output can be arranged in the common comparison montage.
    if all(Path(d).resolve().parent==output.resolve() for d in directories):montage(summaries,output)
    lines=["# MS2109 measured color probe","",f"Analysis UTC: {datetime.now(timezone.utc).isoformat()}","",
        "96 RGB patches on the 1920×1080 HDMI TO USB extended display. Values below are medians of each patch interior across stable frames. A smaller direct YUV residual indicates a closer matrix/range model. Source RGB means the AppKit render in the active display profile; late white-point adjustments can change the HDMI pixels.","",
        "| Run | Active format | Best direct model | YUV RMSE (codes) | Gray black Y/Cb/Cr | Gray white Y/Cb/Cr |",
        "|---|---|---|---:|---|---|"]
    for s in summaries:
        b=s["best_direct_model"];gray=s["gray"]
        lines.append(f"| {s['run']} | {s['actual_active_subtype']} {1/s['actual_frame_duration']:.2f} fps | {b['matrix']} {b['range']} | {b['direct_yuv_rmse']:.3f} | {gray[0]['yuv']} | {gray[-1]['yuv']} |")
    for s in summaries:
        lines += ["",f"## {s['run']}","","| Matrix | Range | Direct YUV RMSE | RGB gain fit, holdout YUV RMSE |","|---|---|---:|---:|"]
        for m in sorted(s["models"],key=lambda m:m["direct_yuv_rmse"]):lines.append(f"| {m['matrix']} | {m['range']} | {m['direct_yuv_rmse']:.3f} | {m['gain_fit_holdout_yuv_rmse']:.3f} |")
        if s["macos_color_state"]:
            lines += ["", "Mac color state: `"+json.dumps(s["macos_color_state"],sort_keys=True)+"`."]
        lines += ["",f"Source render/reference RMSE: {s['source_render_rgb_rmse']:.3f} RGB codes. Maximum temporal patch span: {s['maximum_patch_temporal_span']:.1f} YUV codes. Empirical affine model holdout residual: {s['affine_holdout_yuv_rmse']:.3f} YUV codes.","",
            f"Evidence: [{s['run']}/capture.json]({s['run']}/capture.json), [{s['run']}/analysis.json]({s['run']}/analysis.json), [{s['run']}/patches.csv]({s['run']}/patches.csv)."]
    lines += ["","## Interpretation boundaries","","Neutral gray must have Cb≈128 and Cr≈128 under both 601 and 709. A colored gray ramp therefore needs an explanation beyond a simple 601/709 inverse mismatch. Source-profile conversion, Night Shift/True Tone, input negotiation, and receiver processing are separate stages.","",
        "An arbitrary fitted 3×3 transform can fit either standard matrix by absorbing their difference. The direct models and the constrained RGB-gain holdout model are reported separately to avoid that false inference.","",
        "No firmware, picture-control registers, display profiles, display modes, or white-point settings are changed by this probe. Capture-session format negotiation is temporary. ScreenCaptureKit framebuffer reference is saved only if Screen Recording permission is already granted; otherwise the reference is the AppKit render.","",
        "Matrix equations: [Linux V4L2 color documentation](https://docs.kernel.org/userspace-api/media/v4l/colorspaces-details.html). macOS configuration-lock sequence follows [FFmpeg AVFoundation acquisition](https://github.com/FFmpeg/FFmpeg/blob/master/libavdevice/avfoundation.m)."]
    (output/"report.md").write_text("\n".join(lines)+"\n")
    for s in summaries:
        b=s["best_direct_model"];print(s["run"],b["matrix"],b["range"],"RMSE",round(b["direct_yuv_rmse"],3),"white",s["gray"][-1]["yuv"])


def read_controls(out, name):
    r=subprocess.run(["python3",str(ROOT/"tools/ms2109_hid.py"),"inspect"],capture_output=True,text=True)
    (out/name).write_text(r.stdout if r.returncode==0 else json.dumps({"error":r.stderr,"returncode":r.returncode}))


def acquire(out, spaces, frames, transport):
    out=Path(out).resolve()
    if out.exists():raise ValueError("Refusing to overwrite an existing acquisition directory")
    out.mkdir(parents=True)
    write_json(out/"pattern.json",pattern())
    frameworks=["Cocoa","AVFoundation","CoreMedia","CoreVideo","CoreGraphics","ImageIO","UniformTypeIdentifiers","ScreenCaptureKit"]
    with tempfile.TemporaryDirectory(prefix="ms2109-color-probe-") as td:
        binary=Path(td)/"probe"
        command=["clang","-fobjc-arc","-Wno-deprecated-declarations"]
        for f in frameworks:command += ["-framework",f]
        subprocess.run(command+[str(ROOT/"tools/color_probe_macos.m"),"-o",str(binary)],check=True)
        inventory=subprocess.run([str(binary),"list"],capture_output=True,text=True,check=True)
        (out/"inventory.json").write_text(inventory.stdout)
        read_controls(out,"procamp-before.json")
        directories=[]
        for space in spaces:
            # Keep CoreBrightness/private status queries out of the AVFoundation
            # acquisition process: loading that framework caused black buffers
            # on this host. Status is observed by a separate short-lived process.
            state_before=json.loads(subprocess.run([str(binary),"list"],capture_output=True,text=True,check=True).stdout)["macos_color_state"]
            run=out/f"{space}-{transport}"
            with (out/f"{run.name}.log").open("w") as log:
                subprocess.run([str(binary),"--manifest",str(out/"pattern.json"),"--output",str(run),"--render-space",space,"--transport",transport,"--frames",str(frames)],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=45)
            state_after=json.loads(subprocess.run([str(binary),"list"],capture_output=True,text=True,check=True).stdout)["macos_color_state"]
            metadata=json.loads((run/"capture.json").read_text())
            metadata["macos_color_state"]=state_before;metadata["macos_color_state_end"]=state_after
            write_json(run/"capture.json",metadata)
            directories.append(run)
        read_controls(out,"procamp-after.json")
    analyze(directories,out)
    hashes={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob("*")) if p.is_file()}
    write_json(out/"sha256.json",hashes)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    run=sub.add_parser("run");run.add_argument("--output",type=Path,required=True);run.add_argument("--spaces",nargs="+",choices=["native","srgb"],default=["native","srgb"]);run.add_argument("--frames",type=int,default=8);run.add_argument("--transport",choices=["yuv","avf420v"],default="yuv")
    an=sub.add_parser("analyze");an.add_argument("directories",nargs="+",type=Path);an.add_argument("--output",type=Path,required=True)
    comp=sub.add_parser("compare");comp.add_argument("native",type=Path);comp.add_argument("decoded",type=Path);comp.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.command=="run":
        if not 3<=args.frames<=100:parser.error("--frames must be 3..100")
        if len(set(args.spaces))!=len(args.spaces):parser.error("duplicate rendering spaces")
        acquire(args.output,args.spaces,args.frames,args.transport)
    elif args.command=="compare":compare_transports(args.native,args.decoded,args.output)
    else:analyze(args.directories,args.output)

if __name__=="__main__":main()
