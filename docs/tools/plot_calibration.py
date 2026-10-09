#!/usr/bin/env python3
"""File-only plots of the measured calibration winners, using ReportLab."""
import argparse
import json
from pathlib import Path
from reportlab.graphics.shapes import Drawing,String,Rect
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics import renderSVG
from reportlab.lib import colors

p=argparse.ArgumentParser(description=__doc__);p.add_argument("run",type=Path);p.add_argument("--output",type=Path,required=True);args=p.parse_args()
result=json.loads((args.run/"result.json").read_text());winner=result["best_full_ycbcr"]["sample_id"]
baseline=json.loads((args.run/"sample-000.json").read_text());calibrated=json.loads((args.run/f"sample-{winner:03d}.json").read_text())
d=Drawing(1120,850);c=calibrated["controls"]
d.add(Rect(0,0,1120,850,fillColor=colors.white,strokeColor=None))
d.add(String(35,810,"MS2109 measured range calibration",fontSize=22))
d.add(String(35,782,f"Brightness UI {c['brightness_ui']} (signed {c['brightness_signed']}), contrast {c['contrast']}, saturation {c['saturation']}",fontSize=13))
series_colors=["#777777","#20835f","#e06c1b","#263a85"]
for panel,(title,component,group) in enumerate([("Gray: Y",0,0),("Blue: Cb",1,3),("Red: Cr",2,1),("Gray shadows: Y",0,0)]):
    plot=LinePlot();plot.x=75+panel%2*550;plot.y=145+(1-panel//2)*285;plot.width=450;plot.height=205;plot.joinedLines=1
    start,end=(0,20) if panel==3 else (0,255)
    selected=[(baseline,"yuy2"),(calibrated,"yuy2"),(calibrated,"mjpeg")]
    data=[]
    for sample,mode in selected:
        values=sample["formats"][mode]["median_values"]
        data.append([(i,values[group*256+i][component]) for i in range(start,end+1)])
    ideal=[(start,start if component==0 else 128+start/2),(end,end if component==0 else min(255,128+end/2))]
    plot.data=data+[ideal];plot.xValueAxis.valueMin=start;plot.xValueAxis.valueMax=end
    plot.yValueAxis.valueMin=0;plot.yValueAxis.valueMax=38 if panel==3 else 260
    plot.xValueAxis.valueSteps=[0,5,10,15,20] if panel==3 else [0,64,128,192,255]
    plot.yValueAxis.valueSteps=[0,10,20,30] if panel==3 else [0,64,128,192,255]
    for i,color in enumerate(series_colors):
        plot.lines[i].strokeColor=colors.HexColor(color);plot.lines[i].strokeWidth=1.6
        if i==3: plot.lines[i].strokeDashArray=[4,4]
    d.add(plot);d.add(String(plot.x,plot.y+228,title,fontSize=16));d.add(String(plot.x+120,plot.y-36,"RGB input code",fontSize=12))
for i,(label,color) in enumerate(zip(["Original YUY2","Calibrated YUY2","Calibrated MJPEG","Full-range 709 target"],series_colors)):
    d.add(String(35+i%2*540,55+i//2*22,label,fontSize=13,fillColor=colors.HexColor(color)))
d.add(String(35,18,"Original USB samples; JPEG decoded directly to YCbCr. No host RGB conversion or ICC transform.",fontSize=11))
if args.output.suffix.lower()==".pdf":
    from reportlab.graphics import renderPDF
    renderPDF.drawToFile(d,str(args.output))
else:
    renderSVG.drawToFile(d,str(args.output))
print(args.output)
