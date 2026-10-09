import sys,subprocess,tempfile,os,json,shutil,hashlib,time
from pathlib import Path
root=Path.cwd();sys.path.insert(0,str(root/'tools'))
from calibrate_colors import Client,compile_tools,chart,analyze_sample,write_json
run=root/'artifacts/color-probe/20261006-calibrated-startup-steady'
write_json(run/'pattern.json',chart())
sources=run/'sources';sources.mkdir()
for name in ['calibrate_colors.py','calibrate_uvc_server.c','run_capture_video_uvc_admin.m','color_probe_macos.m','decode_jpeg_ycbcr.c','probe_colors.py']:shutil.copy2(root/'tools'/name,sources/name)
with tempfile.TemporaryDirectory(prefix='ms2109-startup-steady-') as temporary:
 td=Path(temporary);os.chmod(td,0o700);b=compile_tools(td)
 write_json(run/'binary-sha256.json',{k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in b.items()})
 with (run/'capture.log').open('x') as log:
  process=subprocess.Popen([str(b['admin']),str(b['server']),str(b['display']),str(run/'pattern.json'),str(run/'usb'),'calibrate'],stdout=log,stderr=subprocess.STDOUT)
  client=Client(run,process)
  try:
   ready=client.wait(run/'usb/ready.json',300);o=ready['original']
   if o!={'brightness_ui':110,'brightness_signed':-18,'contrast':149,'saturation':147,'hue':0}:raise ValueError('Startup controls changed')
   print('Steady UVC handle ready; startup controls confirmed.',flush=True)
   client.wait(run/'usb-source/display-ready.json',10)
   inventory=subprocess.run([str(b['display']),'list'],capture_output=True,text=True,check=True)
   (run/'inventory-during.json').write_text(inventory.stdout)
   for i in range(2):
    if i:
     fresh=run/'source-after-claim'
     with (run/'repaint.log').open('x') as f:
      chart_process=subprocess.Popen([str(b['display']),'--manifest',str(run/'pattern.json'),'--output',str(fresh),'--transport','display','--render-space','native','--seconds','30'],stdout=f,stderr=subprocess.STDOUT)
      try:
       for _ in range(100):
        if (fresh/'display-ready.json').exists():break
        if chart_process.poll() is not None:raise RuntimeError('Fresh chart exited')
        time.sleep(.05)
       else:raise RuntimeError('Fresh chart unavailable')
       time.sleep(2)
       client.request(f'{i} 110 149 147\n');client.wait(run/f'usb/response-{i:03d}.json',65)
      finally:
       if chart_process.poll() is None:chart_process.terminate()
       chart_process.wait(timeout=5)
    else:
     client.request(f'{i} 110 149 147\n');client.wait(run/f'usb/response-{i:03d}.json',65)
    r=analyze_sample(run,i,b['decode'],td)
    print('Sample',i,'YUY2 full RMSE',r['formats']['yuy2']['full']['rmse_per_channel'],'MJPEG',r['formats']['mjpeg']['full']['rmse_per_channel'],flush=True)
  finally:client.stop()
  if process.returncode:raise RuntimeError('Capture helper failed')
