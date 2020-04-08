# Ref: SX1272 Datasheet
# Accession: G00051

import enum

from ...support.bitstruct import *


__all__ = [
    # Register addresses
    "ADDR_OP_MODE", "ADDR_BITRATE_MSB", "ADDR_BITRATE_LSB", "ADDR_F_DEV_MSB",
    "ADDR_F_DEV_LSB", "ADDR_RX_CONFIG", "ADDR_RSSI_CONFIG",
    "ADDR_RSSI_COLLISION", "ADDR_RSSI_THRESH", "ADDR_RSSI_VALUE",
    "ADDR_RX_BW", "ADDR_AFC_BW", "ADDR_OOK_PEAK", "ADDR_OOK_FIX",
    "ADDR_OOK_AVG", "ADDR_AFC_FEI", "ADDR_AFC_MSB", "ADDR_AFC_LSB",
    "ADDR_FEI_MSB", "ADDR_FEI_LSB", "ADDR_PREAMBLE_DETECT",
    "ADDR_RX_TIMEOUT_1", "ADDR_RX_TIMEOUT_2", "ADDR_RX_TIMEOUT_3",
    "ADDR_RX_DELAY", "ADDR_OSC", "ADDR_PREAMBLE_MSB", "ADDR_PREAMBLE_LSB",
    "ADDR_SYNC_CONFIG", "ADDR_SYNC_VALUE_1", "ADDR_SYNC_VALUE_2",
    "ADDR_SYNC_VALUE_3", "ADDR_SYNC_VALUE_4", "ADDR_SYNC_VALUE_5",
    "ADDR_SYNC_VALUE_6", "ADDR_SYNC_VALUE_7", "ADDR_SYNC_VALUE_8",
    "ADDR_PACKET_CONFIG_1", "ADDR_PACKET_CONFIG_2", "ADDR_PAYLOAD_LENGTH",
    "ADDR_NODE_ADRS", "ADDR_BROADCAST_ADRS", "ADDR_FIFO_THRESH",
    "ADDR_SEQ_CONFIG_1", "ADDR_SEQ_CONFIG_2", "ADDR_TIMER_RESOL",
    "ADDR_TIMER_1_COEF", "ADDR_TIMER_2_COEF", "ADDR_IMAGE_CAL", "ADDR_TEMP",
    "ADDR_LOW_BAT", "ADDR_IRQ_FLAGS_1", "ADDR_IRQ_FLAGS_2",
    # Registers
    "REG_OP_MODE", "REG_RX_CONFIG", "REG_RSSI_CONFIG", "REG_RX_BW",
    "REG_AFC_BW", "REG_OOK_PEAK", "REG_OOK_AVG", "REG_AFC_FEI",
    "REG_PREAMBLE_DETECT", "REG_OSC", "REG_SYNC_CONFIG",
    "REG_PACKET_CONFIG_1", "REG_PACKET_CONFIG_2", "REG_FIFO_THRESH",
    "REG_SEQ_CONFIG_1", "REG_SEQ_CONFIG_2", "REG_TIMER_RESOL",
    "REG_IMAGE_CAL", "REG_LOW_BAT", "REG_IRQ_FLAGS_1", "REG_IRQ_FLAGS_2",
    # Enumerations
    "RSSISMOOTHING", "RXBWMANT", "OOKPEAKTHRESHSTEP", "OOKTHRESHTYPE",
    "OOKPEAKTHREASHDEC", "OOKAVGOFFSET", "OOKAVGTHRESHFILT",
    "AFCAUTOCLEARON", "PREAMBLEDETECTORON", "PREAMBLEDETECTORSIZE", "CLKOUT",
    "AUTORESTARTRXMODE", "PREAMBLEPOLARITY", "SYNCON", "FIFOFILLCONDITION",
    "PACKETFORMAT", "DCFREEENCODING", "CRCON", "CRCAUTOCLEAR",
    "ADDRESSFILTERING", "WHITENINGTYPE", "DATAMODE", "TXSTARTCONDITION",
    "IDLEMODE", "FROMSTART", "LOWPOWERSELECTION", "FROMIDLE", "FROMTRANSMIT",
    "FROMPACKETRECEIVED", "FROMRXTIMEOUT", "FROMRECEIVE", "TIMERRES",
    "TEMPCHANGE", "TEMPTHRESHOLD", "LOWBATTTRIM", "LONGRANGEMODE",
    "MODULATIONTYPE", "MODULATIONSHAPINGFSK", "MODULATIONSHAPINGOOK", "MODE"
]

# Register addresses

ADDR_OP_MODE                 = 0x01
ADDR_BITRATE_MSB             = 0x02
ADDR_BITRATE_LSB             = 0x03
ADDR_F_DEV_MSB               = 0x04
ADDR_F_DEV_LSB               = 0x05
ADDR_RX_CONFIG               = 0x0D
ADDR_RSSI_CONFIG             = 0x0E
ADDR_RSSI_COLLISION          = 0x0F
ADDR_RSSI_THRESH             = 0x10
ADDR_RSSI_VALUE              = 0x11
ADDR_RX_BW                   = 0x12
ADDR_AFC_BW                  = 0x13
ADDR_OOK_PEAK                = 0x14
ADDR_OOK_FIX                 = 0x15
ADDR_OOK_AVG                 = 0x16
ADDR_AFC_FEI                 = 0x1A
ADDR_AFC_MSB                 = 0x1B
ADDR_AFC_LSB                 = 0x1C
ADDR_FEI_MSB                 = 0x1D
ADDR_FEI_LSB                 = 0x1E
ADDR_PREAMBLE_DETECT         = 0x1F
ADDR_RX_TIMEOUT_1            = 0x20
ADDR_RX_TIMEOUT_2            = 0x21
ADDR_RX_TIMEOUT_3            = 0x22
ADDR_RX_DELAY                = 0x23
ADDR_OSC                     = 0x24
ADDR_PREAMBLE_MSB            = 0x25
ADDR_PREAMBLE_LSB            = 0x26
ADDR_SYNC_CONFIG             = 0x27
ADDR_SYNC_VALUE_1            = 0x28
ADDR_SYNC_VALUE_2            = 0x29
ADDR_SYNC_VALUE_3            = 0x2A
ADDR_SYNC_VALUE_4            = 0x2B
ADDR_SYNC_VALUE_5            = 0x2C
ADDR_SYNC_VALUE_6            = 0x2D
ADDR_SYNC_VALUE_7            = 0x2E
ADDR_SYNC_VALUE_8            = 0x2F
ADDR_PACKET_CONFIG_1         = 0x30
ADDR_PACKET_CONFIG_2         = 0x31
ADDR_PAYLOAD_LENGTH          = 0x32
ADDR_NODE_ADRS               = 0x33
ADDR_BROADCAST_ADRS          = 0x34
ADDR_FIFO_THRESH             = 0x35
ADDR_SEQ_CONFIG_1            = 0x36
ADDR_SEQ_CONFIG_2            = 0x37
ADDR_TIMER_RESOL             = 0x38
ADDR_TIMER_1_COEF            = 0x39
ADDR_TIMER_2_COEF            = 0x3A
ADDR_IMAGE_CAL               = 0x3B
ADDR_TEMP                    = 0x3C
ADDR_LOW_BAT                 = 0x3D
ADDR_IRQ_FLAGS_1             = 0x3E
ADDR_IRQ_FLAGS_2             = 0x3F


# Registers

class LONGRANGEMODE(enum.IntEnum):
    _FSK_OOK = 0b0
    _LORA    = 0b1

class MODULATIONTYPE(enum.IntEnum):
    _FSK = 0b00
    _OOK = 0b01

class MODULATIONSHAPINGFSK(enum.IntEnum):
    _NONE = 0b00
    _GAUS_1_0 = 0b01
    _GAUS_0_5 = 0b10
    _GAUS_0_3 = 0b11

class MODULATIONSHAPINGOOK(enum.IntEnum):
    _NONE = 0b00
    _F_BITRATE = 0b01
    _F_2_BITRATE = 0b10

class MODE(enum.IntEnum):
    _SLEEP = 0b000
    _STDBY = 0b001
    _FSTX = 0b010
    _TX = 0b011
    _FSRX = 0b100
    _RX = 0b101

REG_OP_MODE = bitstruct("REG_OP_MODE", 8, [
    ("MODE", 3),
    ("MODULATION_SHAPING", 2),
    ("MODULATION_TYPE", 2),
    ("LONG_RANGE_MODE", 1)
])

REG_RX_CONFIG = bitstruct("REG_RX_CONFIG", 8, [
    ("RX_TRIGGER", 3),
    ("AGC_AUTO_ON", 1),
    ("AFC_AUTO_ON", 1),
    ("RESTART_RX_WITH_PLL_LOCK", 1),
    ("RESTART_RX_WITHOUT_PLL_LOCK", 1),
    ("RESTART_RX_ON_COLLISION", 1)
])

class RSSISMOOTHING(enum.IntEnum):
    _2_SAMPLES = 0b000
    _4_SAMPLES = 0b001
    _8_SAMPLES = 0b010
    _16_SAMPLES = 0b011
    _32_SAMPLES = 0b100
    _64_SAMPLES = 0b101
    _128_SAMPLES = 0b110
    _256_SAMPLES = 0b111

REG_RSSI_CONFIG = bitstruct("REG_RSSI_CONFIG", 8, [
    ("RSSI_SMOOTHING", 3),
    ("RSSI_OFFSET", 5)
])

class RXBWMANT(enum.IntEnum):
    _RX_BW_MANT_16 = 0b00
    _RX_BW_MANT_20 = 0b01
    _RX_BW_MANT_24 = 0b10

REG_RX_BW = bitstruct("REG_RX_BW", 8, [
    ("RX_BW_EXP", 3),
    ("RX_BW_MANT", 2),
    (None, 3)
])

REG_AFC_BW = bitstruct("REG_AFC_BW", 8, [
    ("RX_BW_EXP_AFC", 3),
    ("RX_BW_MANT_AFC", 2),
    (None, 3)
])

class OOKPEAKTHRESHSTEP(enum.IntEnum):
    _0_5_dB = 0b000
    _1_0_dB = 0b001
    _1_5_dB = 0b010
    _2_0_dB = 0b011
    _3_0_dB = 0b100
    _4_0_dB = 0b101
    _5_0_dB = 0b110
    _6_0_dB = 0b111

class OOKTHRESHTYPE(enum.IntEnum):
    _THRESH_FIXED = 0b00
    _THRESH_PEAK = 0b01
    _THRESH_AVG = 0b10

REG_OOK_PEAK = bitstruct("REG_OOK_PEAK", 8, [
    ("OOK_PEAK_THRESH_STEP", 3),
    ("OOK_THRESH_TYPE", 2),
    ("BIT_SYNC_ON", 1),
    (None, 2)
])

class OOKPEAKTHREASHDEC(enum.IntEnum):
    _ONCE_PER_CHIP = 0b000
    _ONCE_EVERY_2_CHIPS = 0b001
    _ONCE_EVERY_4_CHIPS = 0b010
    _ONCE_EVERY_8_CHIPS = 0b011
    _TWICE_EACH_CHIP = 0b100
    _4_TIMES_EACH_CHIP = 0b101
    _8_TIMES_EACH_CHIP = 0b110
    _16_TIMES_EACH_CHIP = 0b111

class OOKAVGOFFSET(enum.IntEnum):
    _0_dB = 0b00
    _2_dB = 0b01
    _4_dB = 0b10
    _6_dB = 0b11

class OOKAVGTHRESHFILT(enum.IntEnum):
    _CHRATE_OVER_32_PI = 0b00
    _CHRATE_OVER_8_PI = 0b01
    _CHRATE_OVER_4_PI = 0b10
    _CHRATE_OVER_2_PI = 0b11

REG_OOK_AVG = bitstruct("REG_OOK_AVG", 8, [
    ("OOK_AVG_THRESH_FILT", 2),
    ("OOK_AVG_OFFSET", 2),
    (None, 1),
    ("OOK_PEAK_THRESH_DEC", 3)
])

REG_AFC_FEI = bitstruct("REG_AFC_FEI", 8, [
    ("AFC_AUTO_CLEAR_ON", 1),
    ("AFC_CLEAR", 1),
    (None, 2),
    ("AFC_START", 1),
    (None, 3)
])

class PREAMBLEDETECTORSIZE(enum.IntEnum):
    _1_BYTE = 0b00
    _2_BYTE = 0b01
    _3_BYTE = 0b10

REG_PREAMBLE_DETECT = bitstruct("REG_PREAMBLE_DETECT", 8, [
    ("PREAMBLE_DETECTOR_TOL", 5),
    ("PREAMBLE_DETECTOR_SIZE", 2),
    ("PREAMBLE_DETECTOR_ON", 1)
])

class CLKOUT(enum.IntEnum):
    _FXOSC = 0b000
    _FXOSC_OVER_2 = 0b001
    _FXOSC_OVER_4 = 0b010
    _FXOSC_OVER_8 = 0b011
    _FXOSC_OVER_16 = 0b100
    _FXOSC_OVER_32 = 0b101
    _RC = 0b110
    _OFF = 0b111

REG_OSC = bitstruct("REG_OSC", 8, [
    ("CLK_OUT", 3),
    ("RC_CAL_START", 1),
    (None, 4)
])

class AUTORESTARTRXMODE(enum.IntEnum):
    _MODE_OFF = 0b00
    _MODE_ON_WAIT_RELOCK = 0b01
    _MODE_ON_WAIT_LOCK = 0b10

class PREAMBLEPOLARITY(enum.IntEnum):
    _AA = 0b0
    _55 = 0b1

class SYNCON(enum.IntEnum):
    _SYNC_OFF = 0b0
    _SYNC_ON = 0b1

class FIFOFILLCONDITION(enum.IntEnum):
    _COND_SYNC_INT = 0b0
    _COND_FILL = 0b1

REG_SYNC_CONFIG = bitstruct("REG_SYNC_CONFIG", 8, [
    ("SYNC_SIZE", 3),
    ("FIFO_FILL_CONDITION", 1),
    ("SYNC_ON", 1),
    ("PREAMBLE_POLARITY", 1),
    ("AUTOSTART_RX_MODE", 2)
])

class PACKETFORMAT(enum.IntEnum):
    _FIXED_LENGTH = 0b0
    _VARIABLE_LENGTH = 0b1

class DCFREEENCODING(enum.IntEnum):
    _NONE = 0b00
    _MANCHESTER = 0b01
    _WHITENING = 0b10

class ADDRESSFILTERING(enum.IntEnum):
    _NONE = 0b00
    _NODE_ONLY = 0b01
    _NODE_OR_BROADCAST = 0b10

class WHITENINGTYPE(enum.IntEnum):
    _CCITT = 0b0
    _IBM = 0b1

REG_PACKET_CONFIG_1 = bitstruct("REG_PACKET_CONFIG_1", 8, [
    ("CRC_WHITENING_TYPE", 1),
    ("ADDRESS_FILTERING", 2),
    ("CRC_AUTO_CLEAR_OFF", 1),
    ("CRC_ON", 1),
    ("DC_FREE", 2),
    ("PACKET_FORMAT", 1)
])

class DATAMODE(enum.IntEnum):
    _CONTINUOUS = 0b0
    _PACKET = 0b1

REG_PACKET_CONFIG_2 = bitstruct("REG_PACKET_CONFIG_2", 8, [
    ("PAYLOAD_LENGTH_10_8", 3),
    ("BEACON_ON", 1),
    ("IO_HOME_POWER_FRAME", 1),
    ("IO_HOME_ON", 1),
    ("DATA_MODE", 1),
    (None, 1)
])

class TXSTARTCONDITION(enum.IntEnum):
    _FIFO_LEVEL = 0b0
    _FIFO_EMPTY = 0b1

REG_FIFO_THRESH = bitstruct("REG_FIFO_THRESH", 8, [
    ("FIFO_THRESHOLD", 6),
    (None, 1),
    ("TX_START_CONDITION", 1)
])

class IDLEMODE(enum.IntEnum):
    _STANDBY = 0b0
    _SLEEP = 0b1

class FROMSTART(enum.IntEnum):
    _TO_LOWPOWER = 0b00
    _TO_RECEIVE = 0b01
    _TO_TRANSMIT = 0b10
    _TO_TX_ON_FIFO = 0b11

class LOWPOWERSELECTION(enum.IntEnum):
    _SEQUENCER_OFF = 0b0
    _IDLE = 0b1

class FROMIDLE(enum.IntEnum):
    _TO_TRANSMIT = 0b0
    _TO_RECEIVE = 0b1

class FROMTRANSMIT(enum.IntEnum):
    _TO_LOWPOWER = 0b0
    _TO_RECEIVE = 0b1

REG_SEQ_CONFIG_1 = bitstruct("REG_SEQ_CONFIG_1", 8, [
    ("FROM_TRANSMIT", 1),
    ("FROM_IDLE", 1),
    ("LOW_POWER_SELECTION", 1),
    ("FROM_START", 2),
    ("IDLE_MODE", 1),
    ("SEQUENCER_STOP", 1),
    ("SEQUENCER_START", 1)
])

class FROMPACKETRECEIVED(enum.IntEnum):
    _TO_SEQUENCER_OFF = 0b000
    _TO_TRANSMIT = 0b001
    _TO_LOWPOWER = 0b010
    _TO_RECEIVE_FS = 0b011
    _TO_RECEIVE = 0b100

class FROMRXTIMEOUT(enum.IntEnum):
    _TO_RECEIVE = 0b00
    _TO_TRANSMIT = 0b01
    _TO_LOWPOWER = 0b10
    _TO_SEQUENCER_OFF = 0b11

class FROMRECEIVE(enum.IntEnum):
    _TO_PACKET_RECEIVED_PAYLOAD_READY = 0b001
    _TO_LOWPOWER = 0b010
    _TO_PACKET_RECEIVED_CRC_OK = 0b011
    _TO_SEQ_OFF_RSSI = 0b100
    _TO_SEQ_OFF_SYNC = 0b101
    _TO_SEQ_OFF_PREAMBLE = 0b110

REG_SEQ_CONFIG_2 = bitstruct("REG_SEQ_CONFIG_2", 8, [
    ("FROM_PACKET_RECEIVED", 3),
    ("FROM_RX_TIMEOUT", 2),
    ("FROM_RECEIVE", 3)
])

class TIMERRES(enum.IntEnum):
    _DISABLED = 0b00
    _64_us = 0b01
    _4100_us = 0b10
    _262_ms = 0b11

REG_TIMER_RESOL = bitstruct("REG_TIMER_RESOL", 8, [
    ("TIMER_2_RESOLUTION", 2),
    ("TIMER_1_RESOLUTION", 2),
    (None, 4)
])

class TEMPCHANGE(enum.IntEnum):
    _TEMP_LOWER = 0b0
    _TEMP_HIGHER = 0b1

class TEMPTHRESHOLD(enum.IntEnum):
    _5_DEG = 0b00
    _10_DEG = 0b01
    _15_DEG = 0b10
    _20_DEG = 0b11

REG_IMAGE_CAL = bitstruct("REG_IMAGE_CAL", 8, [
    ("TEMP_MONITOR_OFF", 1),
    ("TEMP_THRESHOLD", 2),
    ("TEMP_CHANGE", 1),
    (None, 1),
    ("IMAGE_CAL_RUNNING", 1),
    ("IMAGE_CAL_START", 1),
    ("AUTO_IMAGE_CAL_ON", 1)
])

class LOWBATTTRIM(enum.IntEnum):
    _1695_mV = 0b000
    _1764_mV = 0b001
    _1835_mV = 0b010
    _1905_mV = 0b011
    _1976_mV = 0b100
    _2045_mV = 0b101
    _2116_mV = 0b110
    _2185_mV = 0b111

REG_LOW_BAT = bitstruct("REG_TEMP", 8, [
    ("LOW_BAT_TRIM", 3),
    ("LOW_BAT_ON", 1),
    (None, 4)
])

REG_IRQ_FLAGS_1 = bitstruct("REG_IRQ_FLAGS_1", 8, [
    ("SYNC_ADDRESS_MATCH", 1),
    ("PREAMBLE_DETECT", 1),
    ("TIMEOUT", 1),
    ("RSSI", 1),
    ("PLL_LOCK", 1),
    ("TX_READY", 1),
    ("RX_READY", 1),
    ("MODE_READY", 1)
])

REG_IRQ_FLAGS_2 = bitstruct("REG_IRQ_FLAGS_2", 8, [
    ("LOW_BAT", 1),
    ("CRC_OK", 1),
    ("PAYLOAD_READY", 1),
    ("PACKET_SENT", 1),
    ("FIFO_OVERRUN", 1),
    ("FIFO_LEVEL", 1),
    ("FIFO_EMPTY", 1),
    ("FIFO_FULL", 1)
])
