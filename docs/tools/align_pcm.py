"""Drop one initial 16-bit sample from raw MS2109 PCM, preserving chunk boundaries.

Input/output: S16_LE interleaved stereo at 48 kHz. Use only on an uncorrected
stream that still contains the MS2109 initial extra sample. Never apply after
Linux ALSA's built-in correction, or blindly to recordings trimmed by an API.
"""
import sys

class Aligner:
    def __init__(self):
        self.skip = 2
        self.pending = b''
    def feed(self, chunk):
        skipped = min(self.skip, len(chunk))
        self.skip -= skipped
        self.pending += chunk[skipped:]
        count = len(self.pending) // 4 * 4
        result, self.pending = self.pending[:count], self.pending[count:]
        return result
    def finish(self):
        if self.skip:
            raise ValueError('Stream ended before the initial sample was read')
        # A final 16-bit half-frame is expected when the original stream had a
        # whole-frame length. Do not invent its missing partner.
        if len(self.pending) not in (0,2):
            raise ValueError('Truncated 16-bit PCM sample')
        self.pending = b''

if __name__ == '__main__':
    a = Aligner()
    while chunk := sys.stdin.buffer.read(65536):
        sys.stdout.buffer.write(a.feed(chunk))
    a.finish()
