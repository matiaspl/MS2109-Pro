"""Temporary atomic endpoint-register probe via Patch_Common. No EEPROM writes."""
from pathlib import Path
import time,json
from ms2109_hid import Device

class Probe:
    @staticmethod
    def build_code(stream_start_reset=False):
        # Original descriptor/procamp hook first. Preserve every affected
        # register, disable interrupts while accessing banked USB registers.
        code=bytearray.fromhex('12d2b8 c0e0 c082 c083 c0d0 c0f0 c0a8 c2af c093')
        if stream_start_reset:
            # The stream monitor must run before the mailbox's idle fast path;
            # otherwise ordinary main-loop calls return without polling IRAM 3A.
            armed_check=len(code); code+=bytes.fromhex('90de2b e0 6000')
            alt_check=len(code); code+=bytes.fromhex('e53a b40100')
            already_check=len(code); code+=bytes.fromhex('90de2a e0 7000')
            code+=bytes.fromhex('90de2a 7401 f0 90de2c 7401 f0 759302 75800d 75800d 758005')
            reset_jump=len(code); code+=bytes.fromhex('8000')
            not_stream=len(code); code+=bytes.fromhex('90de2a e4 f0')
            poll_done=len(code)
            code[armed_check+5]=poll_done-armed_check-6
            code[alt_check+4]=not_stream-alt_check-5
            code[already_check+5]=poll_done-already_check-6
            code[reset_jump+1]=poll_done-reset_jump-2
            assert all(0 <= code[i] < 128 for i in
                       (armed_check+5, alt_check+4, already_check+5, reset_jump+1))
        code+=bytes.fromhex('90de20 e0')
        jz=len(code)
        code+=bytes.fromhex('70 03 02 00 00') if stream_start_reset else b'\x60\x00'
        code+=bytes.fromhex('f5f0 90de21 e0 f593 e5f0')
        cjne=len(code); code+=bytes.fromhex('b40200')
        code+=bytes.fromhex('90de22 e0 f5a2 a3 e0 f5a3')
        snapshot=len(code)
        code+=bytes.fromhex('e5f0')
        fifo_check=len(code); code+=bytes.fromhex('b40300')
        code+=bytes.fromhex('90de29 e5ad f0 a3 e5ad f0')
        after_fifo=len(code)
        code[fifo_check+2]=after_fifo-fifo_check-3
        # Candidate: insert one silent 16-bit word into endpoint 2's FIFO.
        # AD is inferred from the ROM's AB (EP0) and AE (EP3) FIFO ports.
        code+=bytes.fromhex('e5f0')
        insert_check=len(code); code+=bytes.fromhex('b40400')
        code+=bytes.fromhex('e4 f5ad f5ad')
        code[insert_check+2]=len(code)-insert_check-3
        # The endpoint upper CSR resembles MUSB: bit 4 is DMA enable.
        # Test insertion while DMA is gated, then restore the exact upper CSR.
        code+=bytes.fromhex('e5f0')
        dma_check=len(code); code+=bytes.fromhex('b40500')
        code+=bytes.fromhex('c090 5390ef e4 f5ad f5ad d280 d090')
        code[dma_check+2]=len(code)-dma_check-3
        code+=bytes.fromhex('e5f0')
        reset_check=len(code); code+=bytes.fromhex('b40600')
        code+=bytes.fromhex('75800d 75800d 758005')
        code[reset_check+2]=len(code)-reset_check-3
        code+=bytes.fromhex('90de24 e580 f0 a3 e590 f0 a3 e5a2 f0 a3 e5a3 f0 a3 e593 f0 90de20 e4 f0')
        done=len(code)
        code+=bytes.fromhex('d093 d0a8 d0f0 d0d0 d083 d082 d0e0 22')
        if stream_start_reset:
            code[jz+3:jz+5]=(0xd400+done).to_bytes(2,'big')
        else:
            code[jz+1]=done-jz-2
            assert done-jz-2 < 128, 'JZ displacement must remain signed positive'
        code[cjne+2]=snapshot-cjne-3
        if len(code)>256:
            raise ValueError(f'RAM probe code exceeds preserved window: {len(code)} bytes')
        return bytes(code)

    def __init__(self, stream_start_reset=False):
        self.d=Device()
        self.entry=self.d.read('ram',0xcc00,3)
        if self.entry!=bytes.fromhex('12d2b8'):
            self.d.close(); raise RuntimeError('Unexpected qualified firmware entry')
        self.hooks=self.d.read('ram',0xcbd4,1)
        self.mail=self.d.read('ram',0xde20,16)
        self.old=self.d.read('ram',0xd400,256)
        self.installed=False
        self.stream_start_reset=stream_start_reset
        self.code=self.build_code(stream_start_reset)
        try:
            self.write(0xde20,b'\x00')
            if stream_start_reset:
                self.write(0xde2a,b'\x00\x00\x00')
            self.write(0xd400,self.code)
            self.write(0xcbd4,bytes([self.hooks[0]&~1])); time.sleep(.02)
            self.installed=True
            self.write(0xcc00,bytes.fromhex('12d400'))
            self.write(0xcbd4,self.hooks)
        except BaseException:
            self.close(); raise
    def write(self,addr,data):
        for i,v in enumerate(data): self.d.exchange(0xb6,addr+i,v)
    def command(self,bank,value=None, action=None):
        self.write(0xde21,bytes([bank]))
        if value is not None: self.write(0xde22,value.to_bytes(2,'little'))
        self.write(0xde20,bytes([action or (1 if value is None else 2)]))
        deadline=time.monotonic()+1
        while self.d.read('ram',0xde20,1)!=b'\x00':
            if time.monotonic()>deadline: raise RuntimeError('Probe mailbox timed out')
            time.sleep(.01)
        data=self.d.read('ram',0xde24,5)
        return dict(zip(('csr','config','a2','a3','index'),data))
    def close(self):
        if self.installed:
            if self.stream_start_reset:
                self.write(0xde2b,b'\x00')
            self.write(0xcbd4,bytes([self.hooks[0]&~1])); time.sleep(.02)
            self.write(0xcc00,self.entry)
            self.write(0xcbd4,self.hooks)
        self.write(0xd400,self.old)
        self.write(0xde20,self.mail)
        assert self.d.read('ram',0xcc00,3)==self.entry
        self.d.close()

if __name__=='__main__':
    p=Probe()
    try:
        Path('artifacts/audio-endpoint-probe.bin').write_bytes(p.code)
        results={i:p.command(i) for i in range(5)}
        print(json.dumps(results,indent=2))
        Path('artifacts/audio-endpoint-registers.json').write_text(json.dumps(results,indent=2)+'\n')
    finally:
        p.close(); print('Original common hook restored')
