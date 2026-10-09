#!/usr/bin/env python3
"""Build absolute-luma ROI histograms and an interactive SVG dashboard for native 1080p captures.

Reads saved YUY2 captures only. It does not access or write the USB device.
"""
import argparse
import hashlib
import html
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from analyze_scaler_roi import edge_profile, roi_slice


ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts/scaler-f9a0"
CHART = ART / "test-chart-1920x1080.png"
SOURCE_RENDER = ART / "chart-session-20261007-001220-51789/source-render.png"
SIZE = (1920, 1080)
ROI_PITCHES = {
    "B1 vertical bars": (32, 16, 8, 4, 2),
    "C1 grids": (16, 8, 4, 2, 1),
}
CASES = {
    "20": ("native-luma-identity-fe84-lower-20261007", "fe84-20.yuy2"),
    "30": ("native-luma-identity-fe84-lower-20261007", "fe84-30.yuy2"),
    "40": ("native-luma-identity-fe84-lower-20261007", "fe84-40.yuy2"),
    "60": ("native-luma-identity-fe84-low-20261007", "fe84-60.yuy2"),
    "68": ("native-luma-identity-fe84-low-20261007", "fe84-68.yuy2"),
    "70": ("native-luma-identity-fe84-low-20261007", "fe84-70.yuy2"),
    "74": ("native-luma-identity-fe84-20261007", "fe84-74.yuy2"),
    "7A": ("native-luma-identity-fe84-20261007", "fe84-7a.yuy2"),
    "80": ("native-luma-identity-fe84-20261007", "fe84-80.yuy2"),
}
COLORS = {
    "20": "#0072B2",
    "30": "#E69F00",
    "40": "#009E73",
    "60": "#D55E00",
    "68": "#CC79A7",
    "70": "#56B4E9",
    "74": "#AA4499",
    "7A": "#332288",
    "80": "#B07C00",
}
DASHES = ("", "8 4", "3 3", "10 3 2 3", "2 2", "12 4", "5 2 1 2", "7 3", "1 3")
def grayscale(path):
    array = np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)
    if not (np.array_equal(array[..., 0], array[..., 1]) and
            np.array_equal(array[..., 1], array[..., 2])):
        raise ValueError(f"Expected neutral grayscale chart: {path}")
    return array[..., 0]


def full_rgb_to_limited_y(rgb_gray):
    """Encode full-range gray RGB luma into nominal limited-range 8-bit Y.

    The integer floor matches the saved FE84=40 captures for this chart. This
    is a candidate range model, not a claim about which physical stage applies it.
    """
    wide = rgb_gray.astype(np.uint16)
    return (16 + (219 * wide // 255)).astype(np.uint8)


def histogram(samples):
    counts = np.bincount(samples.ravel(), minlength=256).astype(np.float64)
    total = int(counts.sum())
    fractions = counts / max(total, 1)
    return {
        "fraction_by_y": fractions.round(10).tolist(),
        "sample_count": total,
        "mean_y": round(float(np.mean(samples)), 4),
        "std_y": round(float(np.std(samples)), 4),
        "p05_y": round(float(np.percentile(samples, 5)), 4),
        "median_y": round(float(np.percentile(samples, 50)), 4),
        "p95_y": round(float(np.percentile(samples, 95)), 4),
        "min_y": int(np.min(samples)),
        "max_y": int(np.max(samples)),
    }


def load_y(path):
    raw = Path(path).read_bytes()
    frame_bytes = SIZE[0] * SIZE[1] * 2
    if not raw or len(raw) % frame_bytes:
        raise ValueError(f"Invalid 1920x1080 YUY2 length for {path}: {len(raw)}")
    packed = np.frombuffer(raw, dtype=np.uint8).reshape(-1, SIZE[1], SIZE[0], 2)
    return raw, packed[..., 0]


def roi_samples(image, roi_name, index):
    y_slice, x_slice = roi_slice(roi_name, index, SIZE)
    return image[..., y_slice, x_slice]


def edge_to_codes(profile):
    low = profile["low_plateau_y"]
    high = profile["high_plateau_y"]
    values = [low + y * (high - low) for y in profile["normalized_y"]]
    return {
        "x_px": profile["x_px"],
        "y_codes": [round(float(v), 4) if math.isfinite(v) else None for v in values],
        "low_plateau_y": low,
        "high_plateau_y": high,
        "overshoot_codes": profile["overshoot_codes"],
        "undershoot_codes": profile["undershoot_codes"],
        "polarity": profile["polarity"],
    }


def svg_hist(title, xlabel, series, x_domain, y_domain, x_ticks, y_ticks):
    width, height = 1100, 590
    left, right, top, bottom = 82, 30, 82, 72
    plot_w, plot_h = width - left - right, height - top - bottom

    def xmap(value):
        return left + (value - x_domain[0]) / (x_domain[1] - x_domain[0]) * plot_w

    def ymap(value):
        return top + plot_h - (value - y_domain[0]) / (y_domain[1] - y_domain[0]) * plot_h

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">']
    out.append('<rect width="100%" height="100%" fill="#fff"/>')
    out.append(f'<text x="{left}" y="35" class="title">{html.escape(title)}</text>')
    for tick in y_ticks:
        y = ymap(tick)
        out.append(f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" class="grid"/>')
        out.append(f'<text x="{left-12}" y="{y+5:.2f}" text-anchor="end" class="tick">{tick:g}</text>')
    for tick in x_ticks:
        x = xmap(tick)
        out.append(f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{height-bottom}" class="grid light"/>')
        out.append(f'<text x="{x:.2f}" y="{height-bottom+25}" text-anchor="middle" class="tick">{tick:g}</text>')
    out.append(f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" fill="none" class="axis"/>')
    for index, item in enumerate(series):
        color = item["color"]
        dash = item.get("dash", DASHES[index % len(DASHES)])
        values = item["values"]
        if len(values) == 256:
            points = " ".join(f'{xmap(i):.2f},{ymap(v):.2f}' for i, v in enumerate(values))
            tag = "polyline"
            path_attrs = f'points="{points}"'
        else:
            points = " ".join(f'{xmap(x):.2f},{ymap(v):.2f}' for x, v in zip(item["x"], values) if v is not None)
            tag = "polyline"
            path_attrs = f'points="{points}"'
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        out.append(f'<{tag} {path_attrs} fill="none" stroke="{color}" stroke-width="2.7"{dash_attr}/>' )
    out.append(f'<text x="{left + plot_w/2:.2f}" y="{height-18}" text-anchor="middle" class="label">{html.escape(xlabel)}</text>')
    legend_x, legend_y = left, 58
    for index, item in enumerate(series):
        color = item["color"]
        x = legend_x + index * 156
        dash = item.get("dash", DASHES[index % len(DASHES)])
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        out.append(f'<line x1="{x}" y1="{legend_y}" x2="{x+28}" y2="{legend_y}" stroke="{color}" stroke-width="3"{dash_attr}/>' )
        out.append(f'<text x="{x+34}" y="{legend_y+5}" class="legend">{html.escape(item["label"])}</text>')
    out.append('<style>.title{font:600 23px sans-serif;fill:#17202a}.tick{font:15px sans-serif;fill:#4b5563}.label{font:16px sans-serif;fill:#263238}.legend{font:13px sans-serif;fill:#17202a}.grid{stroke:#d9dee5;stroke-width:1}.grid.light{stroke:#eef0f3}.axis{stroke:#687381;stroke-width:1.2}</style>')
    out.append('</svg>')
    return "\n".join(out)


def make_html(data):
    embedded = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    return r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MS2109 native 1080p ROI analysis</title>
<style>
:root{color-scheme:light;--ink:#17202a;--muted:#586474;--line:#d8dee8;--bg:#f3f5f8;--card:#fff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{padding:24px clamp(18px,4vw,56px);background:#132338;color:#fff}h1{margin:0 0 6px;font-size:clamp(24px,3vw,34px)}header p{margin:0;color:#dbe5f0;max-width:1100px}
main{max-width:1680px;margin:0 auto;padding:22px clamp(14px,3vw,42px) 50px}.notice{background:#fff7dd;border:1px solid #ead18a;border-left:5px solid #d19a18;border-radius:8px;padding:12px 16px;margin-bottom:18px}
.controls,.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;box-shadow:0 2px 8px #16283d0b}.controls{padding:16px;margin-bottom:18px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}.controls fieldset{border:0;padding:0;margin:0}.controls legend{font-weight:700;margin-bottom:6px}.series{display:flex;gap:8px 14px;flex-wrap:wrap}.series label{display:flex;align-items:center;gap:5px;white-space:nowrap}.swatch{display:inline-block;width:18px;border-top:3px solid var(--c)}button,select{font:inherit;padding:7px 10px;border:1px solid #aab5c4;border-radius:6px;background:#fff;color:var(--ink)}button{cursor:pointer}button:hover{background:#edf3f9}.selects{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.selects label{display:flex;align-items:center;gap:7px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.panel{padding:14px;min-width:0}.panel h2{font-size:18px;margin:0 0 8px}.panel p{font-size:13px;color:var(--muted);margin:0 0 6px}.panel svg{display:block;width:100%;height:auto;min-height:300px;touch-action:pan-y}.wide{grid-column:1/-1}.meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:8px;margin-top:12px;color:var(--muted);font-size:13px}.meta div{background:#f7f9fb;padding:8px 10px;border-radius:6px}.tooltip{position:fixed;display:none;pointer-events:none;background:#101b2b;color:white;padding:8px 10px;border-radius:6px;font:12px/1.45 ui-monospace,monospace;white-space:pre;z-index:4;box-shadow:0 4px 15px #0003}.caption{font-size:12px;color:var(--muted);margin-top:10px}
@media(max-width:900px){.grid{grid-template-columns:1fr}.wide{grid-column:auto}.panel svg{min-height:260px}}
</style></head><body>
<header><h1>MS2109 native 1080p → 1080p ROI analysis</h1><p>Absolute Y-code histograms from saved 1920×1080 YUY2 captures, compared with the AppKit source render encoded as limited-range Y.</p></header>
<main>
<div class="notice"><strong>Range-aware reference:</strong> the dashed reference is the saved AppKit RGB source render mapped with <code>Y = 16 + floor(219 × RGB/255)</code>. At FE84=40 this predicts the captured luma across the analyzed ROIs and full frame to within one code, outside a small top-right pointer area. The reference is still not a measured HDMI framebuffer, so this strongly supports a full-RGB to limited-Y range conversion but does not locate the conversion stage. The saved native chart has B1 vertical bars and C1 grids, but no B2 horizontal-bar patch.</div>
<section class="controls"><fieldset><legend>FE84 traces</legend><div class="series" id="series"></div></fieldset><div class="selects"><label>Bar period <select id="barPitch"></select></label><label>Grid pitch <select id="gridPitch"></select></label></div><button id="defaults">Show 40 / 7A</button><button id="all">Show all</button><button id="none">Hide captures</button></section>
<section class="grid">
<article class="panel"><h2>B1 vertical bars: ROI luma histogram</h2><p>Full rectangular ROI; all samples pooled across frames. Hover to inspect exact Y-code bins.</p><svg id="barChart" viewBox="0 0 980 440" role="img" aria-label="B1 bar ROI histogram"></svg></article>
<article class="panel"><h2>C1 grids: ROI luma histogram</h2><p>Full rectangular grid ROI, including the one-pixel checker. Dashed trace is the range-converted AppKit render.</p><svg id="gridChart" viewBox="0 0 980 440" role="img" aria-label="C1 grid ROI histogram"></svg></article>
<article class="panel wide"><h2>Edge A: slanted-edge response</h2><p>Phase-binned profile from raw luma. The plot zooms to ±8 pixels around the edge; hover to inspect each visible trace.</p><svg id="edgeChart" viewBox="0 0 1480 460" role="img" aria-label="Slanted edge response"></svg><div class="caption" id="edgeSummary"></div></article>
</section>
<section class="panel" style="margin-top:16px"><h2>Capture and analysis notes</h2><div class="meta" id="metadata"></div><p class="caption">The analyzer pools every Y sample from each saved eight-frame capture. Histograms use raw 8-bit Y values, not per-trace normalization. The original chart PNG contains RGB codes; its Y comparison is the AppKit render after the stated full-to-limited encoding model.</p></section>
</main><div class="tooltip" id="tooltip"></div>
<script>
const DATA = __DATA__;
const SOURCE_LABEL = "AppKit → limited Y";
const colors = {[SOURCE_LABEL]:"#182433", "20":"#0072B2", "30":"#E69F00", "40":"#009E73", "60":"#D55E00", "68":"#CC79A7", "70":"#56B4E9", "74":"#AA4499", "7A":"#332288", "80":"#B07C00"};
const dashes = ["", "8 4", "3 3", "10 3 2 3", "2 2", "12 4", "5 2 1 2", "7 3", "1 3"];
const values = DATA.register_values;
const selected = new Set(["40","7A"]);
const tooltip = document.getElementById("tooltip");
const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
const ns = "http://www.w3.org/2000/svg";
function el(tag, attrs={}, text=""){const n=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);if(text)n.textContent=text;return n;}
function seriesLabels(){return [...values.filter(v=>selected.has(v)),SOURCE_LABEL];}
function dataFor(label, kind, pitch){if(label===SOURCE_LABEL)return DATA.source_limited_y.rois[kind][String(pitch)].fraction_by_y;return DATA.values[label].rois[kind][String(pitch)].fraction_by_y;}
function edgeFor(label){return label===SOURCE_LABEL?DATA.source_limited_y.edge:DATA.values[label].edge;}
function draw(svg, title, series, xDomain, xTicks, yAxisLabel, histogram){
  while(svg.firstChild)svg.removeChild(svg.firstChild);
  const vb=svg.viewBox.baseVal, W=vb.width,H=vb.height, left=78,right=24,top=54,bottom=60,pw=W-left-right,ph=H-top-bottom;
  const maxValue=Math.max(...series.flatMap(s=>s.values.filter(Number.isFinite)),0.001);
  const yMax=histogram?Math.max(0.05,Math.ceil(maxValue*10)/10):Math.ceil((maxValue+1)/10)*10;
  const yMin=histogram?0:Math.floor((Math.min(...series.flatMap(s=>s.values.filter(Number.isFinite)))-1)/10)*10;
  const xMap=x=>left+(x-xDomain[0])/(xDomain[1]-xDomain[0])*pw;
  const yMap=y=>top+ph-(y-yMin)/(yMax-yMin)*ph;
  svg.append(el("text",{x:left,y:29,class:"plotTitle"},title));
  const ticks=histogram?5:5;
  for(let i=0;i<=ticks;i++){const v=yMin+(yMax-yMin)*i/ticks,y=yMap(v);svg.append(el("line",{x1:left,y1:y,x2:W-right,y2:y,class:"gridline"}));svg.append(el("text",{x:left-10,y:y+5,"text-anchor":"end",class:"tick"},histogram?v.toFixed(2):v.toFixed(0)));}
  for(const v of xTicks){const x=xMap(v);svg.append(el("line",{x1:x,y1:top,x2:x,y2:H-bottom,class:"vgrid"}));svg.append(el("text",{x,y:H-bottom+23,"text-anchor":"middle",class:"tick"},String(v)));}
  svg.append(el("rect",{x:left,y:top,width:pw,height:ph,class:"frame"}));
  svg.append(el("text",{x:left+pw/2,y:H-16,"text-anchor":"middle",class:"axisLabel"},histogram?"raw Y code (0–255)":"distance from edge (pixels)"));
  svg.append(el("text",{x:19,y:top+ph/2,transform:`rotate(-90 19 ${top+ph/2})`,"text-anchor":"middle",class:"axisLabel"},yAxisLabel));
  series.forEach((s,index)=>{let points=[];s.values.forEach((v,i)=>{if(!Number.isFinite(v))return;const x=histogram?xMap(i):xMap(s.x[i]);if(x<xMap(xDomain[0])||x>xMap(xDomain[1]))return;points.push(`${x.toFixed(2)},${yMap(v).toFixed(2)}`)});if(points.length){const attrs={points:points.join(" "),fill:"none",stroke:s.color,"stroke-width":s.label===SOURCE_LABEL?2.8:2.2,"vector-effect":"non-scaling-stroke",class:"trace"};if(s.dash)attrs["stroke-dasharray"]=s.dash;const p=el("polyline",attrs);p.append(el("title",{},s.label));svg.append(p);}});
  const legendY=top-14;let lx=left;for(const s of series){const sw=el("line",{x1:lx,y1:legendY,x2:lx+24,y2:legendY,stroke:s.color,"stroke-width":3});if(s.dash)sw.setAttribute("stroke-dasharray",s.dash);svg.append(sw);const t=el("text",{x:lx+30,y:legendY+5,class:"legend"},s.label);svg.append(t);lx+=Math.max(96,42+s.label.length*7.2);}
  svg.onpointermove=event=>{const rect=svg.getBoundingClientRect();const x=(event.clientX-rect.left)/rect.width*W;const code=Math.round(xDomain[0]+(x-left)/pw*(xDomain[1]-xDomain[0]));const lines=[histogram?`Y=${code}`:`x=${(xDomain[0]+(x-left)/pw*(xDomain[1]-xDomain[0])).toFixed(2)} px`];for(const s of series){let i;if(histogram)i=Math.max(0,Math.min(255,code));else {let best=0,dist=Infinity;for(let j=0;j<s.x.length;j++){let d=Math.abs(s.x[j]-(xDomain[0]+(x-left)/pw*(xDomain[1]-xDomain[0])));if(d<dist){dist=d;best=j;}}i=best;}const v=s.values[i];lines.push(`${s.label}: ${Number.isFinite(v)?(histogram?(v*100).toFixed(3)+"%":v.toFixed(2)+" Y"):"n/a"}`);}tooltip.textContent=lines.join("\n");tooltip.style.display="block";tooltip.style.left=(event.clientX+14)+"px";tooltip.style.top=(event.clientY+14)+"px";};
  svg.onpointerleave=()=>tooltip.style.display="none";
  const style=el("style",{},`.plotTitle{font:600 19px system-ui;fill:#17202a}.tick{font:13px system-ui;fill:#4b5563}.axisLabel{font:14px system-ui;fill:#263238}.legend{font:12px system-ui;fill:#263238}.gridline{stroke:#d9dee5;stroke-width:1}.vgrid{stroke:#edf0f3;stroke-width:1}.frame{fill:none;stroke:#677381;stroke-width:1}.trace{stroke-linejoin:round;stroke-linecap:round}`);svg.append(style);
}
function activeSeries(kind,pitch){return seriesLabels().map(label=>({label,color:colors[label],dash:label===SOURCE_LABEL?"7 4":dashes[(values.indexOf(label)+1)%dashes.length],values:dataFor(label,kind,pitch)}));}
function drawAll(){const bp=Number(document.getElementById("barPitch").value),gp=Number(document.getElementById("gridPitch").value);draw(document.getElementById("barChart"),`B1 vertical bars • ${bp}px period`,activeSeries("B1 vertical bars",bp),[0,255],[0,32,64,96,128,160,192,224,255],"fraction of ROI samples / Y code",true);draw(document.getElementById("gridChart"),`C1 grid • ${gp}px cell pitch`,activeSeries("C1 grids",gp),[0,255],[0,32,64,96,128,160,192,224,255],"fraction of ROI samples / Y code",true);const edgeSeries=seriesLabels().map(label=>{const e=edgeFor(label);return {label,color:colors[label],dash:label===SOURCE_LABEL?"7 4":dashes[(values.indexOf(label)+1)%dashes.length],x:e.x_px,values:e.y_codes};});draw(document.getElementById("edgeChart"),"A slanted edge • raw Y codes",edgeSeries,[-8,8],[-8,-6,-4,-2,0,2,4,6,8],"Y code",false);const lines=seriesLabels().map(label=>{const e=edgeFor(label);return `${label}: +${e.overshoot_codes.toFixed(2)} / −${e.undershoot_codes.toFixed(2)} codes`;});document.getElementById("edgeSummary").textContent="Measured edge A overshoot / undershoot: "+lines.join(" · ");}
function setDefaults(vals){selected.clear();for(const v of vals)selected.add(v);document.querySelectorAll("input[data-value]").forEach(input=>input.checked=selected.has(input.dataset.value));drawAll();}
const seriesRoot=document.getElementById("series");for(const v of values){const label=document.createElement("label"),input=document.createElement("input");input.type="checkbox";input.dataset.value=v;input.checked=selected.has(v);input.addEventListener("change",()=>{input.checked?selected.add(v):selected.delete(v);drawAll();});const sw=document.createElement("span");sw.className="swatch";sw.style.setProperty("--c",colors[v]);label.append(input,sw,document.createTextNode("FE84="+v));seriesRoot.append(label);}
function fillSelect(id,opts,initial){const s=document.getElementById(id);for(const x of opts){const o=document.createElement("option");o.value=x;o.textContent=x+" px";s.append(o);}s.value=String(initial);s.addEventListener("change",drawAll);}
fillSelect("barPitch",[32,16,8,4,2],2);fillSelect("gridPitch",[16,8,4,2,1],1);
document.getElementById("defaults").onclick=()=>setDefaults(["40","7A"]);document.getElementById("all").onclick=()=>setDefaults(values);document.getElementById("none").onclick=()=>setDefaults([]);
const meta=DATA.metadata;for(const [k,v] of Object.entries(meta)){const box=document.createElement("div");box.innerHTML=`<strong>${esc(k)}</strong><br>${esc(v)}`;document.getElementById("metadata").append(box);}drawAll();
</script></body></html>'''.replace("__DATA__", embedded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir
    if output.exists() and any(output.iterdir()):
        parser.error(f"refusing to overwrite non-empty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    source = grayscale(CHART)
    metadata = json.loads(CHART.with_suffix(".json").read_text())
    if [metadata["width"], metadata["height"]] != list(SIZE):
        raise ValueError("Expected the original 1920x1080 scaler chart")
    edge_a = next(edge for edge in metadata["edge_rois"] if edge["label"].startswith("A "))

    source_rois = {}
    for roi_name, pitches in ROI_PITCHES.items():
        source_rois[roi_name] = {}
        for index, pitch in enumerate(pitches):
            samples = roi_samples(source, roi_name, index)
            source_rois[roi_name][str(pitch)] = histogram(samples)
    source_render = grayscale(SOURCE_RENDER)
    if source_render.shape != (SIZE[1], SIZE[0]):
        raise ValueError(f"Expected a 1920x1080 AppKit source render: {SOURCE_RENDER}")
    source_limited_y = full_rgb_to_limited_y(source_render)

    source_limited_rois = {}
    for roi_name, pitches in ROI_PITCHES.items():
        source_limited_rois[roi_name] = {}
        for index, pitch in enumerate(pitches):
            samples = roi_samples(source_limited_y, roi_name, index)
            source_limited_rois[roi_name][str(pitch)] = histogram(samples)
    source_edge = edge_to_codes(edge_profile(source_limited_y[None, ...], source_limited_y, edge_a, SIZE))

    captures = {}
    file_hashes = {}
    for value, (session, filename) in CASES.items():
        session_dir = ART / session
        result = json.loads((session_dir / "result.json").read_text())
        if result.get("neutral_ram_controls") != "00809300" or result.get("neutral_uvc_shadows") != "0000800000009300":
            raise ValueError(f"Unexpected neutral control state in {session}")
        if not result.get("eeprom_unchanged") or result.get("firmware_written"):
            raise ValueError(f"Unexpected persistent-write state in {session}")
        sweep_item = next((item for item in result.get("fe84_sweep", []) if item.get("value", "").upper() == value), None)
        if sweep_item is None:
            raise ValueError(f"FE84={value} is absent from {session}/result.json")
        capture = session_dir / filename
        raw, frames = load_y(capture)
        analysis = sweep_item["analysis"]
        if analysis.get("dimensions") != list(SIZE) or analysis.get("frame_count") != int(frames.shape[0]):
            raise ValueError(f"Capture metadata mismatch for FE84={value}")
        roi_data = {}
        for roi_name, pitches in ROI_PITCHES.items():
            roi_data[roi_name] = {}
            for index, pitch in enumerate(pitches):
                samples = roi_samples(frames, roi_name, index)
                roi_data[roi_name][str(pitch)] = histogram(samples)
        measured_edge = edge_to_codes(edge_profile(frames, source_limited_y, edge_a, SIZE))
        difference = np.abs(frames.astype(np.int16) - source_limited_y[None, ...].astype(np.int16))
        outside_overlay = np.ones((SIZE[1], SIZE[0]), dtype=bool)
        outside_overlay[:20, 1900:] = False
        captures_match = {
            "full_frame_with_overlay": {
                "within_1_code_fraction": round(float(np.mean(difference <= 1)), 8),
                "mean_absolute_error": round(float(np.mean(difference)), 6),
                "max_absolute_error": int(np.max(difference)),
            },
            "outside_conservative_top_right_20x20_overlay": {
                "within_1_code_fraction": round(float(np.mean(difference[:, outside_overlay] <= 1)), 8),
                "mean_absolute_error": round(float(np.mean(difference[:, outside_overlay])), 6),
                "max_absolute_error": int(np.max(difference[:, outside_overlay])),
            },
        }
        captures[value] = {
            "file": str(capture.relative_to(ROOT)),
            "session": session,
            "frame_count": int(frames.shape[0]),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "rois": roi_data,
            "edge": measured_edge,
            "source_model_match": captures_match,
        }
        file_hashes[value] = captures[value]["sha256"]

    data = {
        "metadata": {
            "input_and_capture": "1920x1080 HDMI chart to 1920x1080 YUY2",
            "frames_per_register": "8 frames; all ROI samples pooled",
            "control_state": "RAM controls 00809300; UVC shadows 0000800000009300 (neutral state in saved run records)",
            "roi_method": "Absolute 8-bit Y histograms over text-free rectangles; no per-trace normalization. Dashed source is the AppKit RGB render encoded with the full-range RGB gray to limited-range Y model below.",
            "range_model": "Y = 16 + floor(219 * RGB_gray / 255); this matches the FE84=40 capture and is a signal-code comparison model, not proof of which hardware stage applies it.",
            "source_reference_limit": "AppKit source-render PNG is not a measured HDMI framebuffer. It cannot isolate GPU/display encoding from capture-device encoding.",
            "bar_orientation": "B1 vertical line pairs only; the saved native-size chart has no B2 horizontal-bar patch.",
            "registers": "FE84 values span 0x20–0x80 at the saved sampled values; FE84 is restored to 0x7A in each result record.",
            "persistent_state": "All source result records report EEPROM unchanged and firmware_written=false.",
            "FE84=40 range-model fit": "see source_model_match in values. The mapped AppKit render predicts the FE84=40 ROI and edge data exactly; full-frame residuals are at most one code outside the conservative top-right overlay region.",
        },
        "roi_pitches": {name: list(pitches) for name, pitches in ROI_PITCHES.items()},
        "register_values": list(CASES.keys()),
        "source": {"chart_png_rgb": str(CHART.relative_to(ROOT)), "rois": source_rois},
        "source_limited_y": {
            "appkit_source_render": str(SOURCE_RENDER.relative_to(ROOT)),
            "appkit_source_render_sha256": hashlib.sha256(SOURCE_RENDER.read_bytes()).hexdigest(),
            "model": "16 + floor(219 * full_range_gray_RGB / 255)",
            "rois": source_limited_rois,
            "edge": source_edge,
        },
        "values": captures,
    }
    json_path = output / "native-1080-roi.json"
    html_path = output / "native-1080-roi-dashboard.html"
    json_path.write_text(json.dumps(data, indent=2) + "\n")
    html_path.write_text(make_html(data))

    visible = ("40", "7A")
    for roi_name, filename, pitch in (
        ("B1 vertical bars", "native-1080-bars.svg", 2),
        ("C1 grids", "native-1080-grids.svg", 1),
    ):
        series = []
        for value in visible:
            series.append({"label": "FE84=" + value, "color": COLORS[value],
                           "values": captures[value]["rois"][roi_name][str(pitch)]["fraction_by_y"]})
        series.append({"label": "AppKit→limited Y", "color": "#182433", "dash": "7 4",
                       "values": data["source_limited_y"]["rois"][roi_name][str(pitch)]["fraction_by_y"]})
        title = f"Native 1080p • {roi_name} • {pitch}px"
        svg = svg_hist(title, "raw Y code", series, (0, 255), (0, 0.55), [0, 32, 64, 96, 128, 160, 192, 224, 255], [0, .1, .2, .3, .4, .5])
        (output / filename).write_text(svg)

    edge_series = []
    for value in visible:
        edge_series.append({"label": "FE84=" + value, "color": COLORS[value], "x": captures[value]["edge"]["x_px"], "values": captures[value]["edge"]["y_codes"]})
    edge = data["source_limited_y"]["edge"]
    edge_series.append({"label": "AppKit→limited Y", "color": "#182433", "dash": "7 4", "x": edge["x_px"], "values": edge["y_codes"]})
    edge_min = min(v for item in edge_series for v in item["values"] if v is not None)
    edge_max = max(v for item in edge_series for v in item["values"] if v is not None)
    y0, y1 = math.floor((edge_min - 2) / 10) * 10, math.ceil((edge_max + 2) / 10) * 10
    yticks = list(np.linspace(y0, y1, 6))
    (output / "native-1080-edge.svg").write_text(svg_hist(
        "Native 1080p • edge A • FE84 40 / 7A", "distance from edge (pixels)",
        edge_series, (-8, 8), (y0, y1), [-8, -4, 0, 4, 8], yticks))

    summary = {}
    for value, item in captures.items():
        summary[value] = {
            "B1_2px_mean_y": item["rois"]["B1 vertical bars"]["2"]["mean_y"],
            "B1_2px_p05_p95": [item["rois"]["B1 vertical bars"]["2"]["p05_y"], item["rois"]["B1 vertical bars"]["2"]["p95_y"]],
            "C1_1px_mean_y": item["rois"]["C1 grids"]["1"]["mean_y"],
            "edge_A_overshoot_undershoot": [item["edge"]["overshoot_codes"], item["edge"]["undershoot_codes"]],
            "range_model_within_1_code_fraction": item["source_model_match"]["full_frame_with_overlay"]["within_1_code_fraction"],
            "range_model_outside_overlay_within_1_code_fraction": item["source_model_match"]["outside_conservative_top_right_20x20_overlay"]["within_1_code_fraction"],
        }
    print(json.dumps({"dashboard": str(html_path), "data": str(json_path), "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
