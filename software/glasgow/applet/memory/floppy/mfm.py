import logging


__all__ = ["SoftwareMFMDecoder"]


class SoftwareMFMDecoder:
    def __init__(self, logger):
        self._logger    = logger
        self._lock_time = 0
        self._bit_time  = 0

    def _log(self, message, *args):
        self._logger.log(logging.DEBUG, "soft-MFM: " + message, *args)

    def edges(self, bytestream):
        edge_len = 0
        for byte in bytestream:
            edge_len += 1 + byte
            if byte == 0xfd:
                continue
            yield edge_len
            edge_len  = 0

    def bits(self, bytestream):
        prev_byte = 0
        for curr_byte in bytestream:
            if prev_byte != 0xfd:
                yield 1
            for _ in range(curr_byte):
                yield 0
            prev_byte = curr_byte

    def domains(self, bitstream):
        polarity = 1
        for has_edge in bitstream:
            if has_edge:
                polarity *= -1
            yield polarity

    def lock(self, bitstream, *, debug=False,
             nco_init_period=0, nco_min_period=16, nco_max_period=256,
             nco_frac_bits=8, pll_kp_exp=2, pll_gph_exp=1):
        nco_period = nco_init_period << nco_frac_bits
        nco_phase  = 0
        nco_step   = 1 << nco_frac_bits
        nco_clock  = 0
        pll_error  = 0
        pll_feedbk = 0
        bit_curr   = 0

        for has_edge in bitstream:
            if nco_period <  nco_min_period << nco_frac_bits:
                nco_period = nco_min_period << nco_frac_bits
            if nco_period >= nco_max_period << nco_frac_bits:
                nco_period = nco_max_period << nco_frac_bits

            if has_edge:
                bit_curr    = 1
                pll_error   = nco_phase - (nco_period >> 1)
                pll_p_term  = abs(pll_error) >> pll_kp_exp
                pll_gain    = max(1 << pll_gph_exp, pll_p_term)
                if pll_error < 0:
                    pll_feedbk = +1 * pll_gain
                else:
                    pll_feedbk = -1 * pll_gain

            if nco_phase >= nco_period:
                nco_phase   = 0
                if not debug:
                    yield bit_curr
                bit_curr    = 0
            else:
                nco_phase  += nco_step + pll_feedbk
                nco_period -= pll_feedbk >> pll_gph_exp
                pll_feedbk  = 0

            if debug:
                yield (nco_phase  / nco_step,
                       nco_period / nco_step,
                       pll_error  / nco_step)

    def demodulate(self, chipstream):
        shreg  = []
        offset = 0
        synced = False
        prev   = 0
        bits   = []
        while True:
            while len(shreg) < 64:
                try:
                    shreg.append(next(chipstream))
                except StopIteration:
                    return

            synced_now = False
            for sync_offset in (0, 1):
                if shreg[sync_offset:sync_offset + 16] == [0,1,0,0,0,1,0,0,1,0,0,0,1,0,0,1]:
                    if not synced or sync_offset != 0:
                        self._log("sync=K.A1 chip-off=%d", offset + sync_offset)
                    offset += sync_offset + 16
                    shreg   = shreg[sync_offset + 16:]
                    synced  = True
                    prev    = 1
                    bits    = []
                    yield (1, 0xA1)
                    synced_now = True
                if synced_now: break

            if synced_now:
                continue
            elif not synced and len(shreg) >= 1:
                offset += 1
                shreg   = shreg[1:]

            if synced and len(shreg) >= 2:
                if shreg[0:2] == [0,1]:
                    curr = 1
                elif prev == 1 and shreg[0:2] == [0,0]:
                    curr = 0
                elif prev == 0 and shreg[0:2] == [1,0]:
                    curr = 0
                else:
                    synced = False
                    self._log("desync chip-off=%d bitno=%d prev=%d cell=%d%d",
                              offset, len(bits), prev, *shreg[0:2])

                if synced:
                    offset += 2
                    shreg   = shreg[2:]
                    prev    = curr

                    bits.append(curr)
                    if len(bits) == 8:
                        yield (0, sum(bit << (7 - n) for n, bit in enumerate(bits)))
                        bits = []
