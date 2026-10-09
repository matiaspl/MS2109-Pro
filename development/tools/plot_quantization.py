#!/usr/bin/env python3
"""Plot measured quantization ramps with ReportLab, without device access."""
import argparse
import json
import math
from pathlib import Path
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics import renderSVG
from reportlab.lib import colors

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("input", type=Path)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--zoom", nargs=2, type=int, metavar=("START", "END"))
args = parser.parse_args()
data = json.loads(args.input.read_text())
if "usb-current-yuy2" in data:
    data.pop("avf-current-yuy2", None)
start, end = args.zoom or (0, 255)
if not 0 <= start < end <= 255:parser.error("zoom requires 0 <= START < END <= 255")
palette = ["#205c96", "#d0711e", "#429768", "#9b418a", "#9f2828", "#666666"]
drawing = Drawing(1100, 800)
drawing.add(String(30, 765, "MS2109: every 0–255 level on gray and RGB primary ramps", fontSize=20))
for i, group in enumerate(["gray", "red", "green", "blue"]):
    chart = LinePlot(); chart.x = 65+i % 2*535; chart.y = 125+(1-i//2)*295
    chart.width = 440; chart.height = 220; chart.joinedLines = 1
    if group == "gray":
        series = [[(code, patch[0]) for code, patch in enumerate(v[group]["yuv"]) if start <= code <= end] for v in data.values()]
        ideal = [(start, 16+219/255*start), (end, 16+219/255*end)]; title = "Neutral gray: measured Y codes"
    else:
        component = ["red", "green", "blue"].index(group)
        series = [[(code, patch[component]) for code, patch in enumerate(v[group]["rgb709"]) if start <= code <= end] for v in data.values()]
        ideal = [(start, start), (end, end)]; title = f"{group.title()}: RGB inverse with 709 limited"
    chart.data = series+[ideal]
    chart.xValueAxis.valueMin = start; chart.xValueAxis.valueMax = end; chart.xValueAxis.valueSteps = [start, (start+end)//2, end] if args.zoom else [0, 64, 128, 192, 255]
    if args.zoom:
        values = [y for line in series+[ideal] for _, y in line]
        chart.yValueAxis.valueMin = math.floor(min(values))-1; chart.yValueAxis.valueMax = math.ceil(max(values))+1
    else:
        chart.yValueAxis.valueMin = -5; chart.yValueAxis.valueMax = 260; chart.yValueAxis.valueSteps = [0, 64, 128, 192, 255]
    for j in range(len(series)+1):
        chart.lines[j].strokeColor = colors.HexColor(palette[j % len(palette)]) if j < len(series) else colors.HexColor("#aaaaaa")
        chart.lines[j].strokeWidth = 1.5
        if j == len(series): chart.lines[j].strokeDashArray = [4, 4]
    drawing.add(chart); drawing.add(String(chart.x, chart.y+240, title, fontSize=15))
    drawing.add(String(chart.x+130, chart.y-35, "Source input code", fontSize=12))
for j, name in enumerate(data):
    drawing.add(String(30+j % 3*360, 25+(j//3)*20, name, fontSize=12, fillColor=colors.HexColor(palette[j % len(palette)])))
drawing.add(String(30, 690, "RGB plots show the explicit inverse before clipping; gray shows preserved Y values.", fontSize=12))
renderSVG.drawToFile(drawing, str(args.output))
print(args.output)
