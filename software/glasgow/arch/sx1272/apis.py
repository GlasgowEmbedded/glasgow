import logging
import math
import asyncio

from . import regs_common
from . import regs_xxk
from . import regs_lora

__all__ = [
    "RadioSX1272APIXXK", "RadioSX1272APILoRa" 
]

class RadioSX1272APICommon:
    def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    def _log(self, message, *args):
        self._logger.log(self._level, "SX1272 API: " + message, *args)

    async def _get_register(self, cls, addr):
        reg = await self.lower.read_register(addr)
        return cls.from_int(reg)

    async def _set_register(self, cls, addr, reg):
        assert isinstance(reg, cls)
        await self.lower.write_register(addr, reg.to_int())

    async def get_fifo(self, size):
        return await self.lower.read_register_wide(regs_common.ADDR_FIFO, size)

    async def set_fifo(self, data):
        await self.lower.write_register_wide(regs_common.ADDR_FIFO, data)

    async def get_frf(self):
        frf = await self.lower.read_register_wide(regs_common.ADDR_F_RF_MSB, 3)
        frf = int.from_bytes(frf, byteorder='big')
        return frf

    async def set_frf(self, frf):
        assert frf <= 2**24-1
        return await self.lower.write_register_wide(regs_common.ADDR_F_RF_MSB, [frf >> 16, (frf >> 8) & 0xFF, frf & 0xFF])

    async def get_pa_config(self):
        return await self._get_register(regs_common.REG_PA_CONFIG, regs_common.ADDR_PA_CONFIG)

    async def set_pa_config(self, paconfig):
        await self._set_register(regs_common.REG_PA_CONFIG, regs_common.ADDR_PA_CONFIG, paconfig)

    async def set_pa_config_outpower(self, outpower):
        reg = await self.get_pa_config()
        reg.OUT_POWER = outpower

    async def get_pa_ramp(self):
        return await self._get_register(regs_common.REG_PA_RAMP, regs_common.ADDR_PA_RAMP)

    async def set_pa_ramp(self, paramp):
        await self._set_register(regs_common.REG_PA_RAMP, regs_common.ADDR_PA_RAMP, paramp)

    async def set_pa_ramp_parmap(self, paramp):
        assert isinstance(paramp, regs_common.PARAMP)
        reg = await self.get_pa_ramp()
        reg.PA_RAMP = paramp
        await self.set_pa_ramp(reg)

    async def set_pa_ramp_pll(self, pll):
        assert isinstance(pll, regs_common.LOWPLLTX)
        reg = await self.get_pa_ramp()
        reg.LOW_PN_TX_PLL_OFF = pll
        await self.set_pa_ramp(reg)

    async def get_ocp(self):
        return await self._get_register(regs_common.REG_OCP, regs_common.ADDR_OCP)

    async def set_ocp(self, ocp):
        await self._set_register(regs_common.REG_OCP, regs_common.ADDR_OCP, ocp)

    async def set_ocp_on(self, onoff):
        reg = await self.get_ocp()
        reg.OCP_ON = onoff
        await self.set_ocp(reg)

    async def set_ocp_trim(self, trim):
        reg = await self.get_ocp()
        reg.OCP_TRIM = trim
        await self.set_ocp(reg)

    async def get_lna(self):
        return await self._get_register(regs_common.REG_LNA, regs_common.ADDR_LNA)
    
    async def set_lna(self, lna):
        await self._set_register(regs_common.REG_LNA, regs_common.ADDR_LNA, lna)

    async def set_lna_boost(self, boost):
        assert isinstance(boost, regs_common.LNABOOST)
        reg = await self.get_lna()
        reg.LNA_BOOST = boost
        self.set_lna(reg)

    async def set_lna_gain(self, gain):
        assert isinstance(gain, regs_common.LNAGAIN)
        reg = await self.get_lna()
        reg.LNA_GAIN = gain
        self.set_lna(reg)
    
    async def get_dio_mapping_1(self):
        return await self._get_register(regs_common.REG_DIO_MAPPING_1, regs_common.ADDR_DIO_MAPPING_1)

    async def set_dio_mapping_1(self, mapping):
        await self._set_register(regs_common.REG_DIO_MAPPING_1, regs_common.ADDR_DIO_MAPPING_1, mapping)

    async def get_dio_mapping_2(self):
        return await self._get_register(regs_common.REG_DIO_MAPPING_2, regs_common.ADDR_DIO_MAPPING_2)

    async def set_dio_mapping_2(self, mapping):
        await self._set_register(regs_common.REG_DIO_MAPPING_2, regs_common.ADDR_DIO_MAPPING_2, mapping)

    async def set_dio_mapping_2_preambledetect(self, pdetect):
        assert isinstance(pdetect, regs_common.MAPPREAMBLEDETECT)
        reg = await self.get_dio_mapping_2()
        reg.MAP_PREAMBLE_DETECT = pdetect
        self.set_dio_mapping_2(reg)

    async def get_version(self):
        return await self._get_register(regs_common.REG_VERSION, regs_common.ADDR_VERSION)

    async def get_agc_ref(self):
        return await self._get_register(regs_common.REG_AGC_REF, regs_common.ADDR_AGC_REF)

    async def set_agc_ref_level(self, agcreflevel):
        reg = await self.get_agc_ref()
        reg.AGC_REF_LEVEL = agcreflevel
        await self._set_register(regs_common.REG_AGC_REF, regs_common.ADDR_AGC_REF, reg)

    async def get_agc_thres_1(self):
        return await self._get_register(regs_common.REG_AGC_THRESH_1, regs_common.ADDR_AGC_THRESH_1)

    async def set_agc_step_1(self, step):
        reg = await self.get_agc_thres_1()
        reg.AGC_STEP_1 = step
        await self._set_register(regs_common.REG_AGC_THRESH_1, regs_common.ADDR_AGC_THRESH_1, reg)

    async def get_agc_thres_2(self):
        return await self._get_register(regs_common.REG_AGC_THRESH_2, regs_common.ADDR_AGC_THRESH_2)

    async def set_agc_thres_2(self, thres):
        await self._set_register(regs_common.REG_AGC_THRESH_2, regs_common.ADDR_AGC_THRESH_2, thres)

    async def set_agc_step_2(self, step):
        reg = await self.get_agc_thres_2()
        reg.AGC_STEP_2 = step
        await self.set_agc_thres_2(reg)

    async def set_agc_step_3(self, step):
        reg = await self.get_agc_thres_2()
        reg.AGC_STEP_3 = step
        await self.set_agc_thres_2(reg)

    async def get_agc_thres_3(self):
        return await self._get_register(regs_common.REG_AGC_THRESH_3, regs_common.ADDR_AGC_THRESH_3)

    async def set_agc_thres_3(self, thres):
        await self._set_register(regs_common.REG_AGC_THRESH_3, regs_common.ADDR_AGC_THRESH_3, thres)

    async def set_agc_step_4(self, step):
        reg = await self.get_agc_thres_3()
        reg.AGC_STEP_4 = step
        await self.set_agc_thres_3(reg)

    async def set_agc_step_5(self, step):
        reg = await self.get_agc_thres_3()
        reg.AGC_STEP_5 = step
        await self.set_agc_thres_3(reg)

    async def get_pll_hop(self):
        return await self._get_register(regs_common.REG_PLL_HOP, regs_common.ADDR_PLL_HOP)

    async def set_pll_hop(self, pllhop):
        await self._set_register(regs_common.REG_PLL_HOP, regs_common.ADDR_PLL_HOP, pllhop)

    async def set_pll_hop_dutycycle(self, dcycle):
        reg = await self.get_pll_hop()
        reg.PA_MANUAL_DUTY_CYCLE = dcycle
        await self.set_pll_hop(reg)

    async def set_pll_hop_fasthop(self, fasthop):
        assert isinstance(fasthop, regs_common.FASTHOP)
        reg = await self.get_pll_hop()
        reg.FAST_HOP_ON = fasthop
        await self.set_pll_hop(reg)

    async def get_tcxo(self):
        return await self._get_register(regs_common.REG_TCXO, regs_common.ADDR_TCXO)

    async def set_tcxo(self, tcxoon):
        assert isinstance(tcxoon, regs_common.TCXOINPUT)
        reg = regs_common.REG_TCXO()
        reg.TCXO_INPUT_ON = tcxoon
        return await self._set_register(regs_common.REG_TCXO, regs_common.ADDR_TCXO, reg)

    async def get_pa_dac(self):
        return await self._get_register(regs_common.REG_PA_DAC, regs_common.ADDR_PA_DAC)

    async def set_pa_dac(self, padac):
        assert isinstance(padac, regs_common.PADAC)
        reg = regs_common.REG_PA_DAC
        reg.PA_DAC = padac
        await self._set_register(regs_common.REG_PA_DAC, regs_common.ADDR_PA_DAC, reg)

    async def get_pll(self):
        reg = await self._get_register(regs_common.REG_PLL, regs_common.ADDR_PLL)
        return reg.PLL_BANDWIDTH

    async def set_pll(self, pllbw):
        assert isinstance(pllbw, regs_common.PLLBW)
        reg = regs_common.REG_PLL
        reg.PLL_BANDWIDTH = pllbw
        await self._set_register(regs_common.REG_PLL, regs_common.ADDR_PLL, reg)

    async def get_pll_low_pn(self):
        reg = await self._get_register(regs_common.REG_PLL_LOW_PN, regs_common.ADDR_PLL_LOW_PN)
        return reg.PLL_BANDWIDTH

    async def set_pll_low_pn(self, pllbw):
        assert isinstance(pllbw, regs_common.PLLBW)
        reg = regs_common.REG_PLL_LOW_PN
        reg.PLL_BANDWIDTH = pllbw
        await self._set_register(regs_common.REG_PLL_LOW_PN, regs_common.ADDR_PLL_LOW_PN, reg)

    async def get_pa_manual(self):
        reg = await self._get_register(regs_common.REG_PA_MANUAL, regs_common.ADDR_PA_MANUAL)
        return reg.MANUAL_PA_CONTROL

    async def set_pa_manual(self, onoff):
        reg = regs_common.REG_PA_MANUAL
        reg.MANUAL_PA_CONTROL = onoff
        await self._set_register(regs_common.REG_PA_MANUAL, regs_common.ADDR_PA_MANUAL, reg)

    async def get_former_temp(self):
        return await self.lower.read_register(regs_common.ADDR_FORMER_TEMP)

    async def get_bitrate_frac(self):
        reg = await self._get_register(regs_common.REG_BIT_RATE_FRAC, regs_common.ADDR_BIT_RATE_FRAC)
        return reg.BIT_RATE_FRAC

    async def set_bit_rate_frac(self, frac):
        reg = regs_common.REG_BIT_RATE_FRAC
        reg.BIT_RATE_FRAC = frac
        await self._set_register(regs_common.REG_BIT_RATE_FRAC, regs_common.ADDR_BIT_RATE_FRAC, reg)


class RadioSX1272APIXXK(RadioSX1272APICommon):
    def __init__(self, interface, logger):
        super(RadioSX1272APIXXK, self).__init__(interface, logger)

    async def get_opmode(self):
        return await self._get_register(regs_xxk.REG_OP_MODE, regs_xxk.ADDR_OP_MODE)
    
    async def set_opmode(self, opmode):
        await self._set_register(regs_xxk.REG_OP_MODE, regs_xxk.ADDR_OP_MODE, opmode)

    async def set_opmode_mode(self, mode):
        assert isinstance(mode, regs_xxk.MODE)
        reg = await self.get_opmode()
        reg.MODE = mode
        await self.set_opmode(reg)

    async def set_opmode_modshape(self, shape):
        assert isinstance(shape, regs_xxk.MODULATIONSHAPINGFSK) or isinstance(shape, regs_xxk.MODULATIONSHAPINGOOK)
        reg = await self.get_opmode()
        reg.MODULATION_SHAPING = shape
        await self.set_opmode(reg)

    async def set_opmode_modtype(self, modtype):
        assert isinstance(modtype, regs_xxk.MODULATIONTYPE)
        reg = await self.get_opmode()
        reg.MODULATION_TYPE = modtype
        await self.set_opmode(reg)

    async def set_opmode_lora(self, lrmode):
        assert isinstance(lrmode, regs_xxk.LONGRANGEMODE)
        reg = await self.get_opmode()
        reg.LONG_RANGE_MODE = lrmode
        await self.set_opmode(reg)

    async def get_bitrate(self):
        bitrate =  await self.lower.read_register_wide(regs_xxk.ADDR_BITRATE_MSB, 2)
        bitrate = int.from_bytes(bitrate, byteorder='big')
        return bitrate

    async def set_bitrate(self, bitrate):
        assert bitrate <= 2**16-1
        await self.lower.write_register_wide(regs_xxk.ADDR_BITRATE_MSB, [bitrate >> 8, bitrate & 0xFF])

    async def get_fdev(self):
        fdev =  await self.lower.read_register_wide(regs_xxk.ADDR_F_DEV_MSB, 2)
        fdev = int.from_bytes(fdev, byteorder='big')
        return fdev

    async def set_fdev(self, fdev):
        assert fdev <= 2**14-1
        await self.lower.write_register_wide(regs_xxk.ADDR_F_DEV_MSB, [fdev >> 8, fdev & 0xFF], 2)

    async def get_rx_config(self):
        return await self._get_register(regs_xxk.REG_RX_CONFIG, regs_xxk.ADDR_RX_CONFIG)

    async def set_rx_config(self, config):
        await self._set_register(regs_xxk.REG_RX_CONFIG, regs_xxk.ADDR_RX_CONFIG, config)

    async def set_rx_config_restartrxoncollision(self, onoff):
        reg = await self.get_rx_config()
        reg.RESTART_RX_ON_COLLISION = onoff
        await self.set_rx_config(reg)

    async def set_rx_config_restartrxwithoutplllock(self, onoff):
        reg = await self.get_rx_config()
        reg.RESTART_RX_WITHOUT_PLL_LOCK = onoff
        await self.set_rx_config(reg)

    async def set_rx_config_restartrxwithplllock(self, onoff):
        reg = await self.get_rx_config()
        reg.RESTART_RX_WITH_PLL_LOCK = onoff
        await self.set_rx_config(reg)

    async def set_rx_config_afcautoon(self, onoff):
        reg = await self.get_rx_config()
        reg.AFC_AUTO_ON = onoff
        await self.set_rx_config(reg)

    async def set_rx_config_agcautoon(self, onoff):
        reg = await self.get_rx_config()
        reg.AGC_AUTO_ON = onoff
        await self.set_rx_config(reg)

    async def set_rx_config_rxtrigger(self, trigger):
        reg = await self.get_rx_config()
        reg.RX_TRIGGER = trigger
        await self.set_rx_config(reg)

    async def get_rssi_config(self):
        return await self._get_register(regs_xxk.REG_RSSI_CONFIG, regs_xxk.ADDR_RSSI_CONFIG)

    async def set_rssi_config(self, config):
        await self._set_register(regs_xxk.REG_RSSI_CONFIG, regs_xxk.ADDR_RSSI_CONFIG, config)

    async def set_rssi_config_offset(self, offset):
        reg = await self.get_rssi_config()
        reg.RSSI_OFFSET = offset
        await self.set_rssi_config(reg)

    async def set_rssi_config_smoothing(self, smoothing):
        reg = await self.get_rssi_config()
        reg.RSSI_SMOOTHING = smoothing
        await self.set_rssi_config(reg)

    async def get_rssi_collision_threshold(self):
        return await self.lower.read_register(regs_xxk.ADDR_RSSI_COLLISION)

    async def set_rssi_collision_threshold(self, threshold):
        assert threshold <= 2**8 - 1
        await self.lower.write_register(regs_xxk.ADDR_RSSI_COLLISION, threshold)

    async def get_rssi_threshold(self):
        return await self.lower.read_register(regs_xxk.ADDR_RSSI_THRESH)

    async def set_rssi_threshold(self, threshold):
        assert threshold <= 2**8 - 1
        await self.lower.write_register(regs_xxk.ADDR_RSSI_THRESH, threshold)

    async def get_rssi(self):
        return await self.lower.read_register(regs_xxk.ADDR_RSSI_VALUE)

    async def get_rx_bw(self):
        return await self._get_register(regs_xxk.REG_RX_BW, regs_xxk.ADDR_RX_BW)

    async def set_rx_bw(self, reg):
        await self._set_register(regs_xxk.REG_RX_BW, regs_xxk.ADDR_RX_BW, reg)

    async def set_rx_bw_exp(self, value):
        reg = await self.get_rx_bw()
        reg.RX_BW_EXP = value
        self.set_rx_bw(reg)

    async def set_rx_bw_mant(self, mant):
        assert isinstance(mant, regs_xxk.RXBWMANT)
        reg = await self.get_rx_bw()
        reg.RX_BW_MANT = mant
        self.set_rx_bw(reg)

    async def get_afc_bw(self):
        return await self._get_register(regs_xxk.REG_AFC_BW, regs_xxk.ADDR_AFC_BW)

    async def set_afc_bw(self, reg):
        await self._set_register(regs_xxk.REG_AFC_BW, regs_xxk.ADDR_AFC_BW, reg)

    async def set_afc_bw_exp(self, value):
        reg = await self.get_afc_bw()
        reg.RX_BW_EXP_AFC = value
        self.set_afc_bw(reg)

    async def set_afc_bw_mant(self, mant):
        assert isinstance(mant, regs_xxk.RXBWMANT)
        reg = await self.get_afc_bw()
        reg.RX_BW_MANT_AFC = mant
        self.set_afc_bw(reg)

    async def get_ook_peak(self):
        return await self._get_register(regs_xxk.REG_OOK_PEAK, regs_xxk.ADDR_OOK_PEAK)

    async def set_ook_peak(self, reg):
        await self._set_register(regs_xxk.REG_OOK_PEAK, regs_xxk.ADDR_OOK_PEAK, reg)

    async def set_ook_peak_bitsync(self, onoff):
        reg = await self.get_ook_peak()
        reg.BIT_SYNC_ON = onoff
        await self.set_ook_peak(reg)

    async def set_ook_peak_threshtype(self, thtype):
        assert isinstance(thtype, regs_xxk.OOKTHRESHTYPE)
        reg = await self.get_ook_peak()
        reg.OOK_THRESH_TYPE = thtype
        await self.set_ook_peak(reg)

    async def set_ook_peak_threshstep(self, thstep):
        assert isinstance(thstep, regs_xxk.OOKPEAKTHRESHSTEP)
        reg = await self.get_ook_peak()
        reg.OOK_PEAK_THRESH_STEP = thstep
        await self.set_ook_peak(reg)

    async def get_ook_fix(self):
        return await self.lower.read_register(regs_xxk.ADDR_OOK_FIX)

    async def set_ook_fix(self, value):
        assert value <= 2**8 - 1
        await self.lower.write_register(regs_xxk.ADDR_OOK_FIX, value)

    async def get_ook_avg(self):
        return await self._get_register(regs_xxk.REG_OOK_AVG, regs_xxk.ADDR_OOK_AVG)

    async def set_ook_avg(self, reg):
        await self._set_register(regs_xxk.REG_OOK_AVG, regs_xxk.ADDR_OOK_AVG, reg)

    async def set_ook_avg_peakthreshdec(self, value):
        assert isinstance(value, regs_xxk.OOKPEAKTHREASHDEC)
        reg = await self.get_ook_avg()
        reg.OOK_PEAK_THRESH_DEC = value
        await self.set_ook_avg(reg)

    async def set_ook_avg_offset(self, value):
        assert isinstance(value, regs_xxk.OOKAVGOFFSET)
        reg = await self.get_ook_avg()
        reg.OOK_AVG_OFFSET = value
        await self.set_ook_avg(reg)

    async def set_ook_avg_threshfilt(self, value):
        assert isinstance(value, regs_xxk.OOKAVGTHRESHFILT)
        reg = await self.get_ook_avg()
        reg.OOK_AVG_THRESH_FILT = value
        await self.set_ook_avg(reg)

    async def get_afc_fei(self):
        return await self._get_register(regs_xxk.REG_AFC_FEI, regs_xxk.ADDR_AFC_FEI)

    async def set_afc_fei(self, fei):
        await self._set_register(regs_xxk.REG_AFC_FEI, regs_xxk.ADDR_AFC_FEI, fei)

    async def set_afc_fei_autoclear(self, onoff):
        reg = await self.get_afc_fei()
        reg.AFC_AUTO_CLEAR_ON = onoff
        await self.set_afc_fei(reg)

    async def set_afc_fei_agcclear(self, onoff):
        reg = await self.get_afc_fei()
        reg.AFC_CLEAR = onoff
        await self.set_afc_fei(reg)

    async def set_afc_fei_agcstart(self, onoff):
        reg = await self.get_afc_fei()
        reg.AFC_START = onoff
        await self.set_afc_fei(reg)

    async def get_afc(self):
        return await self.lower.get_register_wide(regs_xxk.ADDR_AFC_MSB, 2)

    async def set_afc(self, value):
        await self.lower.write_register_wide(regs_xxk.ADDR_AFC_MSB, [value >> 8, value & 0xFF])

    async def get_fei(self):
        return await self.lower.get_register_wide(regs_xxk.ADDR_FEI_MSB, 2)

    async def set_fei(self, value):
        await self.lower.write_register_wide(regs_xxk.ADDR_FEI_MSB, [value >> 8, value & 0xFF])

    async def get_preamble_detect(self):
        return await self._get_register(regs_xxk.REG_PREAMBLE_DETECT, regs_xxk.ADDR_PREAMBLE_DETECT)

    async def set_preamble_detect(self, pdetect):
        await self._set_register(regs_xxk.REG_PREAMBLE_DETECT, regs_xxk.ADDR_PREAMBLE_DETECT, pdetect)

    async def set_preamble_detect_tol(self, tol):
        reg = await self.get_preamble_detect()
        reg.PREAMBLE_DETECTOR_TOL = tol
        await self.set_preamble_detect(reg)

    async def set_preamble_detect_size(self, size):
        assert isinstance(size, regs_xxk.PREAMBLEDETECTORSIZE)
        reg = await self.get_preamble_detect()
        reg.PREAMBLE_DETECTOR_SIZE = size
        await self.set_preamble_detect(reg)

    async def set_preamble_detect_on(self, onoff):
        reg = await self.get_preamble_detect()
        reg.PREAMBLE_DETECTOR_ON = onoff
        await self.set_preamble_detect(reg)

    async def get_rx_timeout_rssi(self):
        return await self.lower.read_register(regs_xxk.ADDR_RX_TIMEOUT_1)

    async def set_rx_timeout_rssi(self, timeout):
        assert timeout <= 2**8 - 1
        await self.lower.write_register(regs_xxk.ADDR_RX_TIMEOUT_1, timeout)

    async def get_rx_timeout_preamble(self):
        return await self.lower.read_register(regs_xxk.ADDR_RX_TIMEOUT_2)

    async def set_rx_timeout_preamble(self, timeout):
        assert timeout <= 2**8 - 1
        await self.lower.write_register(regs_xxk.ADDR_RX_TIMEOUT_2, timeout)

    async def get_rx_timeout_sync(self):
        return await self.lower.read_register(regs_xxk.ADDR_RX_TIMEOUT_3)

    async def set_rx_timeout_sync(self, timeout):
        assert timeout <= 2**8 - 1
        await self.lower.write_register(regs_xxk.ADDR_RX_TIMEOUT_3, timeout)

    async def get_rx_delay(self):
        return await self.lower.read_register(regs_xxk.ADDR_RX_DELAY)

    async def set_rx_delay(self, value):
        assert value <= 2**8 - 1
        await self.lower.write_register(regs_xxk.ADDR_RX_DELAY, value)

    async def get_osc(self):
        return await self._get_register(regs_xxk.REG_OSC, regs_xxk.ADDR_OSC)

    async def set_osc(self, osc):
        await self._set_register(regs_xxk.REG_OSC, regs_xxk.ADDR_OSC, osc)

    async def set_osc_clkout(self, value):
        assert isinstance(value, regs_xxk.CLKOUT)
        reg = await self.get_osc()
        reg.CLK_OUT = value
        await self.set_osc(reg)

    async def set_osc_calstart(self):
        reg = await self.get_osc()
        reg.RC_CAL_START = 1
        await self.set_osc(reg)

    async def get_preamble_size(self):
        size =  await self.lower.read_register_wide(regs_xxk.ADDR_PREAMBLE_MSB, 2)
        size = int.from_bytes(size, byteorder='big')
        return size

    async def set_preamble_size(self, size):
        assert size <= 2**16 - 1
        await self.lower.write_register_wide(regs_xxk.ADDR_PREAMBLE_MSB, [size >> 8, size & 0xFF])

    async def get_sync_config(self):
        return await self._get_register(regs_xxk.REG_SYNC_CONFIG, regs_xxk.ADDR_SYNC_CONFIG)

    async def set_sync_config(self, config):
        await self._set_register(regs_xxk.REG_SYNC_CONFIG, regs_xxk.ADDR_SYNC_CONFIG, config)

    async def set_sync_config_size(self, size):
        reg = await self.get_sync_config()
        reg.SYNC_SIZE = size
        await self.set_sync_config(reg)

    async def set_sync_config_fillcond(self, cond):
        assert isinstance(cond, regs_xxk.FIFOFILLCONDITION)
        reg = await self.get_sync_config()
        reg.FIFO_FILL_CONDITION = cond
        await self.set_sync_config(reg)

    async def set_sync_config_on(self, onoff):
        reg = await self.get_sync_config()
        reg.SYNC_ON = onoff
        await self.set_sync_config(reg)

    async def set_sync_config_prepolarity(self, pol):
        assert isinstance(pol, regs_xxk.PREAMBLEPOLARITY)
        reg = await self.get_sync_config()
        reg.PREAMBLE_POLARITY = pol
        await self.set_sync_config(reg)

    async def set_sync_config_restartmode(self, mode):
        assert isinstance(mode, regs_xxk.AUTORESTARTRXMODE)
        reg = await self.get_sync_config()
        reg.AUTORESTART_RX_MODE = mode
        await self.set_sync_config(reg)

    async def get_sync_value(self):
        value =  await self.lower.read_register_wide(regs_xxk.ADDR_SYNC_VALUE_1, 8)
        value = int.from_bytes(value, byteorder='big')
        return value

    async def set_sync_value(self, value):
        assert value <= 2**64 - 1
        await self.lower.write_register_wide(regs_xxk.ADDR_SYNC_VALUE_1, [value >> 56, (value >> 48) & 0xFF, (value >> 40) & 0xFF, (value >> 32) & 0xFF, (value >> 24) & 0xFF, (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF])

    async def get_packet_config_1(self):
        return self._get_register(regs_xxk.REG_PACKET_CONFIG_1, regs_xxk.ADDR_PACKET_CONFIG_1)

    async def set_packet_config_1(self, config):
        await self._set_register(regs_xxk.REG_PACKET_CONFIG_1, regs_xxk.ADDR_PACKET_CONFIG_1, config)

    async def set_packet_config_1_whitening(self, wtype):
        assert isinstance(wtype, regs_xxk.WHITENINGTYPE)
        reg = await self.get_packet_config_1()
        reg.CRC_WHITENING_TYPE = wtype
        await self.set_packet_config_1(reg)

    async def set_packet_config_1_filtering(self, config):
        assert isinstance(config, regs_xxk.ADDRESSFILTERING)
        reg = await self.get_packet_config_1()
        reg.ADDRESS_FILTERING = config
        await self.set_packet_config_1(reg)

    async def set_packet_config_1_crcclear(self, offon):
        reg = await self.get_packet_config_1()
        reg.CRC_AUTO_CLEAR_OFF = offon
        await self.set_packet_config_1(reg)

    async def set_packet_config_1_crcon(self, onoff):
        reg = await self.get_packet_config_1()
        reg.CRC_ON = onoff
        await self.set_packet_config_1(reg)

    async def set_packet_config_1_dcfree(self, config):
        assert isinstance(config, regs_xxk.DCFREEENCODING)
        reg = await self.get_packet_config_1()
        reg.DC_FREE = config
        await self.set_packet_config_1(reg)

    async def set_packet_config_1_packetformat(self, format):
        assert isinstance(format, regs_xxk.PACKETFORMAT)
        reg = await self.get_packet_config_1()
        reg.PACKET_FORMAT = format
        await self.set_packet_config_1(reg)

    async def get_packet_config_2(self):
        return self._get_register(regs_xxk.REG_PACKET_CONFIG_2, regs_xxk.ADDR_PACKET_CONFIG_2)

    async def set_packet_config_2(self, config):
        await self._set_register(regs_xxk.REG_PACKET_CONFIG_2, regs_xxk.ADDR_PACKET_CONFIG_2, config)

    async def set_packet_config_2_beaconon(self, onoff):
        reg = await self.get_packet_config_2()
        reg.BEACON_ON = onoff
        await self.set_packet_config_2(reg)

    async def set_packet_config_2_iohomeon(self, onoff):
        reg = await self.get_packet_config_2()
        reg.IO_HOME_ON = onoff
        await self.set_packet_config_2(reg)

    async def set_packet_config_2_datamode(self, mode):
        assert isinstance(mode, regs_xxk.DATAMODE)
        reg = await self.get_packet_config_2()
        reg.DATA_MODE = mode
        await self.set_packet_config_2(reg)

    async def get_payload_length(self):
        pconf2 = await self.get_packet_config_2()
        msb = pconf2.PAYLOAD_LENGTH_10_8
        lsb = await self.lower.read_register(regs_xxk.ADDR_PAYLOAD_LENGTH)
        return (msb << 8) + lsb

    async def set_payload_length(self, value):
        msb = (value >> 8)
        lsb = value & 0xFF
        pconf2 = await self.get_packet_config_2()
        pconf2.PAYLOAD_LENGTH_10_8 = msb
        await self.lower.write_register_wide(regs_xxk.ADDR_PACKET_CONFIG_2, [pconf2, lsb])

    async def get_node_adrs(self):
        return self.lower.read_register(regs_xxk.ADDR_NODE_ADRS)

    async def set_node_adrs(self, adrs):
        assert adrs <= 2**8 - 1
        await self.lower.write_register(regs_xxk.ADDR_NODE_ADRS, adrs)

    async def get_bcast_adrs(self):
        return self.lower.read_register(regs_xxk.ADDR_BROADCAST_ADRS)

    async def set_bcast_adrs(self, adrs):
        assert adrs <= 2**8 - 1
        await self.lower.write_register(regs_xxk.ADDR_BROADCAST_ADRS, adrs)

    async def get_fifo_thresh(self):
        return await self._get_register(regs_xxk.REG_FIFO_THRESH, regs_xxk.ADDR_FIFO_THRESH)

    async def set_fifo_thresh(self, value):
        await self._set_register(regs_xxk.REG_FIFO_THRESH, regs_xxk.ADDR_FIFO_THRESH, value)

    async def set_fifo_thresh_thresh(self, thresh):
        assert thresh <= 2**6 - 1
        reg = await self.get_fifo_thresh()
        reg.FIFO_THRESHOLD = thresh
        await self.set_fifo_thresh(reg)

    async def set_fifo_thresh_txcond(self, cond):
        assert isinstance(cond, regs_xxk.TXSTARTCONDITION)
        reg = await self.get_fifo_thresh()
        reg.TX_START_CONDITION = cond
        await self.set_fifo_thresh(reg)

    async def get_seq_config_1(self):
        return await self._get_register(regs_xxk.REG_SEQ_CONFIG_1, regs_xxk.ADDR_SEQ_CONFIG_1)

    async def set_seq_config_1(self, conf):
        await self._set_register(regs_xxk.REG_SEQ_CONFIG_1, regs_xxk.ADDR_SEQ_CONFIG_1, conf)

    async def set_seq_config_1_fromtx(self, value):
        assert isinstance(value, regs_xxk.FROMTRANSMIT)
        reg = await self.get_seq_config_1()
        reg.FROM_TRANSMIT = value
        await self.set_seq_config_1(reg)

    async def set_seq_config_1_fromidle(self, value):
        assert isinstance(value, regs_xxk.FROMIDLE)
        reg = await self.get_seq_config_1()
        reg.FROM_IDLE = value
        await self.set_seq_config_1(reg)

    async def set_seq_config_1_lpsel(self, value):
        assert isinstance(value, regs_xxk.LOWPOWERSELECTION)
        reg = await self.get_seq_config_1()
        reg.LOW_POWER_SELECTION = value
        await self.set_seq_config_1(reg)

    async def set_seq_config_1_fromstart(self, value):
        assert isinstance(value, regs_xxk.FROMSTART)
        reg = await self.get_seq_config_1()
        reg.FROM_START = value
        await self.set_seq_config_1(reg)

    async def set_seq_config_1_idlemode(self, value):
        assert isinstance(value, regs_xxk.IDLEMODE)
        reg = await self.get_seq_config_1()
        reg.IDLE_MODE = value
        await self.set_seq_config_1(reg)

    async def set_sequencer_stop(self):
        reg = await self.get_seq_config_1()
        reg.SEQUENCER_STOP = 1
        await self.set_seq_config_1(reg)

    async def set_sequencer_start(self):
        reg = await self.get_seq_config_1()
        reg.SEQUENCER_START = 1
        await self.set_seq_config_1(reg)

    async def get_seq_config_2(self):
        return await self._get_register(regs_xxk.REG_SEQ_CONFIG_2, regs_xxk.ADDR_SEQ_CONFIG_2)

    async def set_seq_config_2(self, conf):
        await self._set_register(regs_xxk.REG_SEQ_CONFIG_2, regs_xxk.ADDR_SEQ_CONFIG_2, conf)

    async def set_seq_config_2_frompktrcvd(self, value):
        assert isinstance(value, regs_xxk.FROMPACKETRECEIVED)
        reg = await self.get_seq_config_2()
        reg.FROM_PACKET_RECEIVED = value
        await self.set_seq_config_2(reg)

    async def set_seq_config_2_fromrxtmout(self, value):
        assert isinstance(value, regs_xxk.FROMRXTIMEOUT)
        reg = await self.get_seq_config_2()
        reg.FROM_RX_TIMEOUT = value
        await self.set_seq_config_2(reg)

    async def set_seq_config_2_fromreceive(self, value):
        assert isinstance(value, regs_xxk.FROMRECEIVE)
        reg = await self.get_seq_config_2()
        reg.FROM_RECEIVE = value
        await self.set_seq_config_2(reg)

    async def get_timer_resol(self):
        return await self._get_register(regs_xxk.REG_TIMER_RESOL, regs_xxk.ADDR_TIMER_RESOL)

    async def set_timer_resol(self, value):
        await self._set_register(regs_xxk.REG_TIMER_RESOL, regs_xxk.ADDR_TIMER_RESOL, value)

    async def set_timer_resol_timer1(self, value):
        assert isinstance(value, regs_xxk.TIMERRES)
        reg = await self.get_timer_resol()
        reg.TIMER_1_RESOLUTION = value
        await self.set_timer_resol(reg)

    async def set_timer_resol_timer2(self, value):
        assert isinstance(value, regs_xxk.TIMERRES)
        reg = await self.get_timer_resol()
        reg.TIMER_2_RESOLUTION = value
        await self.set_timer_resol(reg)

    async def get_timer1_coef(self):
        return await self.lower.read_register(regs_xxk.ADDR_TIMER_1_COEF)

    async def set_timer1_coef(self, value):
        assert value <= 2**8 - 1
        await self.lower.write_register(regs_xxk.ADDR_TIMER_1_COEF, value)

    async def get_timer2_coef(self):
        return await self.lower.read_register(regs_xxk.ADDR_TIMER_2_COEF)

    async def set_timer2_coef(self, value):
        assert value <= 2**8 - 1
        await self.lower.write_register(regs_xxk.ADDR_TIMER_2_COEF, value)

    async def get_image_cal(self):
        return await self._get_register(regs_xxk.REG_IMAGE_CAL, regs_xxk.ADDR_IMAGE_CAL)

    async def set_image_cal(self, cal):
        await self._set_register(regs_xxk.REG_IMAGE_CAL, regs_xxk.ADDR_IMAGE_CAL, cal)

    async def set_image_cal_tempmonoff(self, offon):
        reg = await self.get_image_cal()
        reg.TEMP_MONITOR_OFF = offon
        await self.set_image_cal(reg)

    async def set_image_cal_tempthresh(self, thresh):
        assert isinstance(thresh, regs_xxk.TEMPTHRESHOLD)
        reg = await self.get_image_cal()
        reg.TEMP_THRESHOLD = thresh
        await self.set_image_cal(reg)

    async def set_image_cal_tempchange(self, change):
        assert isinstance(change, regs_xxk.TEMPCHANGE)
        reg = await self.get_image_cal()
        reg.TEMP_CHANGE = change
        await self.set_image_cal(reg)

    async def get_image_cal_running(self):
        reg = await self.get_image_cal()
        return reg.IMAGE_CAL_RUNNING

    async def set_image_cal_start(self):
        reg = await self.get_image_cal()
        reg.IMAGE_CAL_START = 1
        await self.set_image_cal(reg)

    async def set_image_cal_autoon(self, onoff):
        reg = await self.get_image_cal()
        reg.AUTO_IMAGE_CAL_ON = onoff
        await self.set_image_cal(reg)

    async def get_temp(self):
        return await self.lower.read_register(regs_xxk.ADDR_TEMP)

    async def get_low_bat(self):
        return await self._get_register(regs_xxk.REG_LOW_BAT, regs_xxk.ADDR_LOW_BAT)

    async def set_low_bat(self, value):
        await self._set_register(regs_xxk.REG_LOW_BAT, regs_xxk.ADDR_LOW_BAT, value)

    async def set_low_bat_trim(self, value):
        assert isinstance(value, regs_xxk.LOWBATTTRIM)
        reg = await self.get_low_bat()
        reg.LOW_BAT_TRIM = value
        await self.set_low_bat(reg)

    async def set_low_bat_on(self, onoff):
        reg = await self.get_low_bat()
        reg.LOW_BAT_ON = onoff
        await self.set_low_bat(reg)

    async def get_irq_flags_1(self):
        return await self._get_register(regs_xxk.REG_IRQ_FLAGS_1, regs_xxk.ADDR_IRQ_FLAGS_1)

    async def set_irq_flags_1(self, flags):
        await self._set_register(regs_xxk.REG_IRQ_FLAGS_1, regs_xxk.ADDR_IRQ_FLAGS_1, flags)

    async def set_irq_flags_1_syncmatch(self):
        reg = regs_xxk.REG_IRQ_FLAGS_1
        reg.SYNC_ADDRESS_MATCH = 1
        await self.set_irq_flags_1(reg)

    async def set_irq_flags_1_predetect(self):
        reg = regs_xxk.REG_IRQ_FLAGS_1
        reg.PREAMBLE_DETECT = 1
        await self.set_irq_flags_1(reg)

    async def set_irq_flags_1_rssi(self):
        reg = regs_xxk.REG_IRQ_FLAGS_1
        reg.RSSI = 1
        await self.set_irq_flags_1(reg)

    async def get_irq_flags_2(self):
        return await self._get_register(regs_xxk.REG_IRQ_FLAGS_2, regs_xxk.ADDR_IRQ_FLAGS_2)

    async def set_irq_flags_2(self, flags):
        await self._set_register(regs_xxk.REG_IRQ_FLAGS_2, regs_xxk.ADDR_IRQ_FLAGS_2, flags)

    async def set_irq_flags_2_lowbat(self):
        reg = regs_xxk.REG_IRQ_FLAGS_2
        reg.LOW_BAT = 1
        await self.set_irq_flags_2(reg)

    async def set_irq_flags_1_fifoovr(self):
        reg = regs_xxk.REG_IRQ_FLAGS_2
        reg.FIFO_OVERRUN = 1
        await self.set_irq_flags_2(reg)


class RadioSX1272APILoRa(RadioSX1272APICommon):
    def __init__(self, interface, logger):
        super(RadioSX1272APILoRa, self).__init__(interface, logger)

    async def get_opmode(self):
        return await self._get_register(regs_lora.REG_OP_MODE, regs_lora.ADDR_OP_MODE)
    
    async def set_opmode(self, opmode):
        await self._set_register(regs_lora.REG_OP_MODE, regs_lora.ADDR_OP_MODE, opmode)

    async def set_opmode_mode(self, mode):
        assert isinstance(mode, regs_lora.MODE)
        reg = await self.get_opmode()
        reg.MODE = mode
        await self.set_opmode(reg)

    async def set_opmode_sharedreg(self, mode):
        assert isinstance(mode, regs_lora.ACCESSSHAREDREG)
        reg = await self.get_opmode()
        reg.ACCESS_SHARED_REG = mode
        await self.set_opmode(reg)

    async def set_opmode_lora(self, lrmode):
        assert isinstance(lrmode, regs_lora.LONGRANGEMODE)
        reg = await self.get_opmode()
        reg.LONG_RANGE_MODE = lrmode
        await self.set_opmode(reg)

    async def get_fifo_addr_ptr(self):
        return await self.lower.read_register(regs_lora.ADDR_FIFO_ADDR_PTR)

    async def set_fifo_addr_ptr(self, value):
        assert value <= 2**8 -1
        await self.lower.write_register(regs_lora.ADDR_FIFO_ADDR_PTR, value)

    async def get_fifo_tx_base_addr(self):
        return await self.lower.read_register(regs_lora.ADDR_FIFO_TX_BASE_ADDR)

    async def set_fifo_tx_base_addr(self, value):
        assert value <= 2**8 -1
        await self.lower.write_register(regs_lora.ADDR_FIFO_TX_BASE_ADDR, value)

    async def get_fifo_rx_base_addr(self):
        return await self.lower.read_register(regs_lora.ADDR_FIFO_RX_BASE_ADDR)

    async def set_fifo_rx_base_addr(self, value):
        assert value <= 2**8 -1
        await self.lower.write_register(regs_lora.ADDR_FIFO_RX_BASE_ADDR, value)

    async def get_fifo_rx_curr_addr(self):
        return await self.lower.read_register(regs_lora.ADDR_FIFO_RX_CURRENT_ADDR)

    async def get_irq_flags_mask(self):
        return await self._get_register(regs_lora.REG_IRQ_FLAGS_MASK, regs_lora.ADDR_IRQ_FLAGS_MASK)

    async def set_irq_flags_mask(self, mask):
        await self._set_register(regs_lora.REG_IRQ_FLAGS_MASK, regs_lora.ADDR_IRQ_FLAGS_MASK, mask)

    async def set_irq_flags_mask_caddet(self, onoff):
        reg = await self.get_irq_flags_mask()
        reg.CAD_DETECTED_MASK = onoff
        await self.set_irq_flags_mask(reg)

    async def set_irq_flags_mask_fhsschn(self, onoff):
        reg = await self.get_irq_flags_mask()
        reg.FHSS_CHANGE_CHANNEL_MASK = onoff
        await self.set_irq_flags_mask(reg)

    async def set_irq_flags_mask_caddone(self, onoff):
        reg = await self.get_irq_flags_mask()
        reg.CAD_DONE_MASK = onoff
        await self.set_irq_flags_mask(reg)

    async def set_irq_flags_mask_txdone(self, onoff):
        reg = await self.get_irq_flags_mask()
        reg.TX_DONE_MASK = onoff
        await self.set_irq_flags_mask(reg)

    async def set_irq_flags_mask_validheader(self, onoff):
        reg = await self.get_irq_flags_mask()
        reg.VALID_HEADER_MASK = onoff
        await self.set_irq_flags_mask(reg)

    async def set_irq_flags_mask_crcerr(self, onoff):
        reg = await self.get_irq_flags_mask()
        reg.PAYLOAD_CRC_ERROR_MASK = onoff
        await self.set_irq_flags_mask(reg)

    async def set_irq_flags_mask_rxdone(self, onoff):
        reg = await self.get_irq_flags_mask()
        reg.RX_DONE_MASK = onoff
        await self.set_irq_flags_mask(reg)

    async def set_irq_flags_mask_rxtimeout(self, onoff):
        reg = await self.get_irq_flags_mask()
        reg.RX_TIMEOUT_MASK = onoff
        await self.set_irq_flags_mask(reg)

    async def get_irq_flags(self):
        return await self._get_register(regs_lora.REG_IRQ_FLAGS, regs_lora.ADDR_IRQ_FLAGS)

    async def set_irq_flags(self, flags):
        await self._set_register(regs_lora.REG_IRQ_FLAGS, regs_lora.ADDR_IRQ_FLAGS, flags)

    async def clear_irq_flags(self):
        reg = regs_lora.REG_IRQ_FLAGS.from_int(0xFF)
        await self.set_irq_flags(reg)

    async def clear_irq_flag_caddet(self):
        reg = await self.get_irq_flags()
        reg.CAD_DETECTED = 1
        await self.set_irq_flags(reg)

    async def clear_irq_flag_fhsschn(self):
        reg = await self.get_irq_flags()
        reg.FHSS_CHANGE_CHANNEL = 1
        await self.set_irq_flags(reg)

    async def clear_irq_flag_caddone(self):
        reg = await self.get_irq_flags()
        reg.CAD_DONE = 1
        await self.set_irq_flags(reg)

    async def clear_irq_flag_txdone(self):
        reg = await self.get_irq_flags()
        reg.TX_DONE = 1
        await self.set_irq_flags(reg)

    async def clear_irq_flag_validheader(self):
        reg = await self.get_irq_flags()
        reg.VALID_HEADER = 1
        await self.set_irq_flags(reg)

    async def clear_irq_flag_crcerr(self):
        reg = await self.get_irq_flags()
        reg.PAYLOAD_CRC_ERROR = 1
        await self.set_irq_flags(reg)

    async def clear_irq_flag_rxdone(self):
        reg = await self.get_irq_flags()
        reg.RX_DONE = 1
        await self.set_irq_flags(reg)

    async def clear_irq_flag_rxtimeout(self):
        reg = await self.get_irq_flags()
        reg.RX_TIMEOUT = 1
        await self.set_irq_flags(reg)

    async def get_rx_nb_bytes(self):
        return await self.lower.read_register(regs_lora.ADDR_RX_NB_BYTES)

    async def get_rx_header_cnt(self):
        cnt = await self.lower.read_register_wide(regs_lora.ADDR_RX_HEADER_CNT_VALUE_MSB, 2)
        return int.from_bytes(cnt, byteorder='big')

    async def get_rx_packet_cnt(self):
        cnt = await self.lower.read_register_wide(regs_lora.ADDR_RX_PACKET_CNT_VALUE_MSB, 2)
        return int.from_bytes(cnt, byteorder='big')

    async def get_modem_stat(self):
        return await self._get_register(regs_lora.REG_MODEM_STAT, regs_lora.ADDR_MODEM_STAT)

    async def get_pkt_snr(self):
        return await self.lower.read_register(regs_lora.ADDR_PKT_SNR_VALUE)

    async def get_pkt_rssi(self):
        return await self.lower.read_register(regs_lora.ADDR_PKT_RSSI_VALUE)

    async def get_rssi(self):
        return await self.lower.read_register(regs_lora.ADDR_RSSI_VALUE)

    async def get_hop_channel(self):
        return await self._get_register(regs_lora.REG_HOP_CHANNEL, regs_lora.ADDR_HOP_CHANNEL)

    async def get_modem_config_1(self):
        return await self._get_register(regs_lora.REG_MODEM_CONFIG_1, regs_lora.ADDR_MODEM_CONFIG_1)

    async def set_modem_config_1(self, config):
        await self._set_register(regs_lora.REG_MODEM_CONFIG_1, regs_lora.ADDR_MODEM_CONFIG_1, config)

    async def set_modem_config_1_ldoptim(self, onoff):
        reg = await self.get_modem_config_1()
        reg.LOW_DATA_RATE_OPTIMIZE = onoff
        await self.set_modem_config_1(reg)

    async def set_modem_config_1_rxcrcon(self, onoff):
        reg = await self.get_modem_config_1()
        reg.RX_PAYLOAD_CRC_ON = onoff
        await self.set_modem_config_1(reg)

    async def set_modem_config_1_headermode(self, mode):
        assert isinstance(mode, regs_lora.HEADERMODE)
        reg = await self.get_modem_config_1()
        reg.IMPLICIT_HEADER_MODE_ON = mode
        await self.set_modem_config_1(reg)

    async def set_modem_config_1_codingrate(self, rate):
        assert isinstance(rate, regs_lora.CODINGRATE)
        reg = await self.get_modem_config_1()
        reg.CODING_RATE = rate
        await self.set_modem_config_1(reg)

    async def set_modem_config_1_bw(self, bw):
        assert isinstance(bw, regs_lora.MODEMBW)
        reg = await self.get_modem_config_1()
        reg.BW = bw
        await self.set_modem_config_1(reg)

    async def get_modem_config_2(self):
        return await self._get_register(regs_lora.REG_MODEM_CONFIG_2, regs_lora.ADDR_MODEM_CONFIG_2)

    async def set_modem_config_2(self, config):
        await self._set_register(regs_lora.REG_MODEM_CONFIG_2, regs_lora.ADDR_MODEM_CONFIG_2, config)

    async def set_modem_config_2_agcon(self, config):
        assert isinstance(config, regs_lora.LNAGAINSOURCE)
        reg = await self.get_modem_config_2()
        reg.AGC_AUTO_ON = config
        await self.set_modem_config_2(reg)

    async def set_modem_config_2_txmode(self, mode):
        assert isinstance(mode, regs_lora.TXMODE)
        reg = await self.get_modem_config_2()
        reg.TX_CONTINUOUS_MODE = mode
        await self.set_modem_config_2(reg)

    async def set_modem_config_2_spreading(self, factor):
        assert isinstance(factor, regs_lora.SPREADINGFACTOR)
        reg = await self.get_modem_config_2()
        reg.SPREADING_FACTOR = factor
        await self.set_modem_config_2(reg)

    async def get_symbol_timeout(self):
        mconfig2 = await self.get_modem_config_2()
        msb = mconfig2.SYMB_TIMEOUT_MSB
        lsb = await self.lower.read_register(regs_lora.ADDR_SYMB_TIMEOUT_LSB)
        return (msb << 8) + lsb

    async def set_symbol_timeout(self, timeout):
        assert timeout <= 2**10 - 1
        msb = (timeout >> 8)
        lsb = timeout & 0xFF
        mconfig2 = await self.get_modem_config_2()
        mconfig2.SYMB_TIMEOUT_MSB = msb
        await self.lower.write_register_wide(regs_lora.ADDR_MODEM_CONFIG_2, [mconfig2.to_int(), lsb])

    async def get_preamble_length(self):
        preamble = await self.lower.read_register_wide(regs_lora.ADDR_PREAMBLE_MSB, 2)
        return int.from_bytes(preamble, byteorder='big')

    async def set_preamble_length(self, preamble):
        assert preamble <= 2**16 - 1
        await self.lower.write_register_wide(regs_lora.ADDR_PREAMBLE_MSB, [preamble >> 8, preamble & 0xFF])

    async def get_payload_length(self):
        return await self.lower.read_register(regs_lora.ADDR_PAYLOAD_LENGTH)

    async def set_payload_length(self, value):
        assert value != 0 and value <= 2**8 - 1
        await self.lower.write_register(regs_lora.ADDR_PAYLOAD_LENGTH, value)

    async def get_payload_max_length(self):
        return await self.lower.read_register(regs_lora.ADDR_MAX_PAYLOAD_LENGTH)

    async def set_payload_max_length(self, value):
        assert value <= 2**8 - 1
        await self.lower.write_register(regs_lora.ADDR_MAX_PAYLOAD_LENGTH, value)

    async def get_hop_period(self):
        return await self.lower.read_register(regs_lora.ADDR_HOP_PERIOD)

    async def set_hop_period(self, value):
        assert value <= 2**8 - 1
        await self.lower.write_register(regs_lora.ADDR_HOP_PERIOD, value)

    async def get_fifo_rx_byte_addr(self):
        return await self.lower.read_register(regs_lora.ADDR_FIFO_RX_BYTE_ADDR)

    async def get_fei(self):
        msb = await self.lower.read_register(regs_lora.ADDR_FEI_MSB)
        lsb = await self.lower.read_register_wide(regs_lora.ADDR_FEI_MID, 2)
        return ((msb & 0x0F) << 16) + int.from_bytes(lsb, byteorder='big')

    async def get_rssi_wideband(self):
        return await self.lower.read_register(regs_lora.ADDR_RSSI_WIDEBAND)

    async def get_detect_optimize(self):
        return await self._get_register(regs_lora.REG_DETECT_OPTIMIZE, regs_lora.ADDR_DETECT_OPTIMIZE)

    async def set_detect_optimize(self, value):
        await self._set_register(regs_lora.REG_DETECT_OPTIMIZE, regs_lora.ADDR_DETECT_OPTIMIZE, value)

    async def set_detect_optimize_optim(self, optim):
        assert isinstance(optim, regs_lora.DETECTOPTIMIZE)
        reg = await self.get_detect_optimize()
        reg.DETECTION_OPTIMIZE = optim
        await self.set_detect_optimize(reg)

    async def set_detect_optimize_if(self, onoff):
        reg = await self.get_detect_optimize()
        reg.AUTOMATIC_IF_ON = onoff
        await self.set_detect_optimize(reg)

    async def get_invert_iq(self):
        return await self._get_register(regs_lora.REG_INVERT_IQ, regs_lora.ADDR_INVERT_IQ)

    async def set_invert_iq(self, reg):
        await self._set_register(regs_lora.REG_INVERT_IQ, regs_lora.ADDR_INVERT_IQ, reg)

    async def set_invert_iq_tx(self, onoff):
        reg = await self.get_invert_iq()
        reg.INVERT_IQTX = onoff
        await self.set_invert_iq(reg)

    async def set_invert_iq_rx(self, onoff):
        reg = await self.get_invert_iq()
        reg.INVERT_IQRX = onoff
        await self.set_invert_iq(reg)
        # Set to 0x19 when RX inverted IQ is set. c.f. AN1200.24
        if onoff == 1:
            await self.lower.write_register(regs_lora.ADDR_INVERT_IQ_2, 0x19)
        else:
            await self.lower.write_register(regs_lora.ADDR_INVERT_IQ_2, 0x1D)

    async def get_detection_threshold(self):
        thresh = regs_lora.DETECTIONTHRESHOLD
        thresh = await self.lower.read_register(regs_lora.ADDR_DETECTION_THRESHOLD)
        return thresh

    async def set_detection_threshold(self, value):
        assert isinstance(value, regs_lora.DETECTIONTHRESHOLD)
        await self.lower.write_register(regs_lora.ADDR_DETECTION_THRESHOLD, value)

    async def get_sync_word(self):
        return await self.lower.read_register(regs_lora.ADDR_SYNC_WORD)

    async def set_sync_word(self, word):
        assert word <= 2**8 - 1
        await self.lower.write_register(regs_lora.ADDR_SYNC_WORD, word)

    async def get_invert_iq_2(self):
        return await self.lower.read_register(regs_lora.ADDR_INVERT_IQ_2)

    async def get_chirp_filter(self):
        return await self.lower.read_register(regs_lora.ADDR_CHIRP_FILTER)

    async def set_chirp_filter(self, value):
        assert value == 0xA0 or value == 0x31
        await self.lower.write_register(regs_lora.ADDR_CHIRP_FILTER, value)
