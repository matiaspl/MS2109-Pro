#!/usr/bin/env python3
"""Plot measured gray-ramp values using ReportLab's scientific line chart API."""
import argparse
import json
from pathlib import Path
from reportlab.graphics.shapes import Drawing,String
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics import renderSVG
from reportlab.lib import colors

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('analyses',nargs='+',type=Path)
p.add_argument('--output',required=True,type=Path)
a=p.parse_args()
runs=[]
for path in a.analyses:
 data=json.loads(path.read_text());runs.extend(data if isinstance(data,list) else [data])
d=Drawing(1200,700)
for index,(label,channel,ymin,ymax) in enumerate([('Luma Y',0,0,255),('Chroma Cb',1,88,148),('Chroma Cr',2,108,158)]):
 chart=LinePlot();chart.x=60+index*400;chart.y=100;chart.width=310;chart.height=480
 series=[[(g['source_code'],g['yuv'][channel]) for g in r['gray']] for r in runs]
 series.append([(0,16 if channel==0 else 128),(255,235 if channel==0 else 128)])
 chart.data=series;chart.joinedLines=1;chart.xValueAxis.valueMin=0;chart.xValueAxis.valueMax=255;chart.xValueAxis.valueSteps=[0,64,128,192,255]
 chart.yValueAxis.valueMin=ymin;chart.yValueAxis.valueMax=ymax;chart.yValueAxis.valueSteps=list(range(ymin,ymax+1,32 if channel==0 else 10))
 palette=[colors.HexColor(c) for c in ['#b35421','#d39243','#12648f','#3a9eac','#7165ab','#9a62aa','#285938']]
 for i in range(len(series)):
  chart.lines[i].strokeColor=palette[i%len(palette)] if i<len(runs) else colors.HexColor('#777777')
  chart.lines[i].strokeWidth=2 if i<len(runs) else 1
  if i==len(runs):chart.lines[i].strokeDashArray=[4,4]
 d.add(chart);d.add(String(chart.x,610,label,fontSize=20));d.add(String(chart.x+50,55,'Source gray code (0–255)',fontSize=13))
d.add(String(30,660,'MS2109 gray-ramp probe — measured YCbCr code values',fontSize=23))
for i,r in enumerate(runs):d.add(String(30+(i%3)*400,20+(i//3)*18,r['run'],fontSize=12,fillColor=palette[i%len(palette)]))
d.add(String(780,640,'Dashed: ideal limited-range neutral gray',fontSize=12,fillColor=colors.HexColor('#777777')))
renderSVG.drawToFile(d,str(a.output))
print(a.output)
