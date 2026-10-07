"""Restore/verify a saved sharpness RAM qualification snapshot."""
import argparse,json,hashlib
from pathlib import Path
from ms2109_hid import Device

EXPECTED="83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82"

def run(source,output):
    record=json.loads(source.read_text())
    if record.get('live_eeprom_sha256_before')!=EXPECTED:
        raise RuntimeError('Snapshot is not from the expected installed EEPROM')
    previous=record['previous_flags']
    ranges={int(address,16):bytes.fromhex(value) for address,value in record['before'].items()}
    d=Device(); result={'status':'restoring RAM snapshot','ranges':len(ranges)}
    try:
        live=d.read('eeprom',0,2048)
        if hashlib.sha256(live).hexdigest()!=EXPECTED:
            raise RuntimeError('Live EEPROM is not the verified rollback image')
        d.exchange(0xB6,0xCBD4,previous&~7)
        for address,data in ranges.items():
            if address==0xCBD0:
                header=bytearray(data);header[4]=previous&~7;data=bytes(header)
            for offset,value in enumerate(data): d.exchange(0xB6,address+offset,value)
        d.exchange(0xB6,0xCBD4,previous)
        result['ram_ranges_match']=all(d.read('ram',address,len(data))==data
                                      for address,data in ranges.items())
        result['flags']=d.read('ram',0xCBD4,1).hex()
        eeprom1=d.read('eeprom',0,2048);eeprom2=d.read('eeprom',0,2048)
        result['eeprom_unchanged']=eeprom1==eeprom2 and hashlib.sha256(eeprom1).hexdigest()==EXPECTED
        result['eeprom_sha256']=hashlib.sha256(eeprom1).hexdigest()
        result['status']='restored and verified' if result['ram_ranges_match'] and result['eeprom_unchanged'] else 'verification failed'
    finally:
        d.close()
    if output.exists():raise RuntimeError(f'Refusing to overwrite {output}')
    output.write_text(json.dumps(result,indent=2)+'\n')
    if result['status']!='restored and verified':raise RuntimeError(result['status'])
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('snapshot',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(run(a.snapshot,a.output),indent=2))
