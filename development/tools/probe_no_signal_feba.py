#!/usr/bin/env python3
"""Reversible sweep of FEBA's lower five bits under confirmed no HDMI."""
import hashlib
import json
import signal
import subprocess
import time
from pathlib import Path
from ms2109_hid import Device

OUT = Path('artifacts/no-signal-feba/trial-03')
VALUES = tuple(range(0x20))


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    d = Device()
    child = None
    original = None
    result = {'scope': 'FEBA lower bits, temporary writes only; AVFoundation YUY2', 'stages': []}

    def save():
        (OUT / 'result.json').write_text(json.dumps(result, indent=2) + '\n')

    def interrupted(signum, frame):
        raise RuntimeError(f'interrupted by signal {signum}')

    signal.signal(signal.SIGTERM, interrupted)
    try:
        d.identify_eeprom()
        before = d.read('eeprom', 0, d.eeprom_size)
        result['eeprom_before_sha256'] = hashlib.sha256(before).hexdigest()
        original = d.read('ram', 0xfeba, 1)[0]
        result['feba_original'] = original
        if original & 0xe0:
            raise RuntimeError(f'Unexpected FEBA high bits {original:02x}; refusing field test')
        if original not in (0x00, 0x08):
            raise RuntimeError(f'Unexpected FEBA {original:02x}; expected known baseline 00 or 08')
        save()
        for value in VALUES:
            stage = {'value': value}
            result['stages'].append(stage)
            d.exchange(0xb6, 0xfeba, value)
            stage['readback_before_capture'] = d.read('ram', 0xfeba, 1)[0]
            if stage['readback_before_capture'] != value:
                raise RuntimeError(f'FEBA readback mismatch for {value:02x}')
            save()
            name = f'feba-{value:02x}'
            with (OUT / f'{name}.log').open('w') as log:
                child = subprocess.Popen([
                    'ffmpeg', '-nostdin', '-hide_banner', '-f', 'avfoundation',
                    '-framerate', '5', '-video_size', '1920x1080', '-pixel_format', 'yuyv422',
                    '-i', 'usb video:none', '-t', '3', '-an', '-r', '5', '-c:v', 'ffv1',
                    str(OUT / f'{name}.mkv')], stdout=log, stderr=log)
                time.sleep(1)
                if child.poll() is not None:
                    raise RuntimeError(f'{name}: capture exited before test interval')
                child.wait(timeout=15)
                stage['capture_returncode'] = child.returncode
                child = None
            if stage['capture_returncode']:
                raise RuntimeError(f'{name}: capture failed; inspect log')
            subprocess.run([
                'ffmpeg', '-nostdin', '-v', 'error', '-sseof', '-0.5', '-i', str(OUT / f'{name}.mkv'),
                '-frames:v', '1', '-update', '1', str(OUT / f'{name}.png')],
                check=True, timeout=10)
            stage['readback_after_capture'] = d.read('ram', 0xfeba, 1)[0]
            stage['last_frame_sha256'] = hashlib.sha256((OUT / f'{name}.png').read_bytes()).hexdigest()
            save()
        d.exchange(0xb6, 0xfeba, original)
        result['feba_restored'] = d.read('ram', 0xfeba, 1)[0]
        after = d.read('eeprom', 0, d.eeprom_size)
        result['eeprom_after_sha256'] = hashlib.sha256(after).hexdigest()
        result['eeprom_unchanged'] = before == after
        if result['feba_restored'] != original or before != after:
            raise RuntimeError('restore verification failed')
        save()
    except BaseException as error:
        result['error'] = str(error)
        save()
        raise
    finally:
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        if original is not None:
            try:
                d.exchange(0xb6, 0xfeba, original)
                result['feba_restored_finally'] = d.read('ram', 0xfeba, 1)[0]
                save()
            except Exception as error:
                result['restore_error'] = str(error)
                save()
        d.close()


if __name__ == '__main__':
    main()
