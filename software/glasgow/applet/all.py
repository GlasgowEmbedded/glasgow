
from .internal.selftest import SelfTestApplet
from .internal.benchmark import BenchmarkApplet

from .interface.uart import UARTApplet
from .interface.spi_master import SPIMasterApplet
from .interface.i2c_initiator import I2CInitiatorApplet
from .interface.i2c_target import I2CTargetApplet
from .interface.jtag_pinout import JTAGPinoutApplet
from .interface.jtag_probe import JTAGProbeApplet
from .interface.jtag_openocd import JTAGOpenOCDApplet
from .interface.jtag_svf import JTAGSVFApplet
from .interface.ps2_host import PS2HostApplet
from .interface.sbw_probe import SpyBiWireProbeApplet

from .memory._24x import Memory24xApplet
from .memory._25x import Memory25xApplet
from .memory.onfi import MemoryONFIApplet
from .memory.floppy import MemoryFloppyApplet

from .debug.arc import DebugARCApplet
from .debug.mips import DebugMIPSApplet
from .debug.arm.swd import DebugARMSWDApplet

from .program.avr.spi import ProgramAVRSPIApplet
from .program.chipcon import ProgramChipconApplet
from .program.ice40_flash import ProgramICE40FlashApplet
from .program.ice40_sram import ProgramICE40SRAMApplet
from .program.m16c import ProgramM16CApplet
from .program.mec16xx import ProgramMEC16xxApplet
from .program.nrf24lx1 import ProgramNRF24Lx1Applet
from .program.xc6s import ProgramXC6SApplet
from .program.xc9500xl import ProgramXC9500XLApplet

from .control.tps6598x import ControlTPS6598xApplet

from .sensor.bmx280 import SensorBMx280Applet
from .sensor.hx711 import SensorHX711Applet
from .sensor.ina260 import SensorINA260Applet
from .sensor.mouse_ps2 import SensorMousePS2Applet
from .sensor.scd30 import SensorSCD30Applet

from .display.hd44780 import DisplayHD44780Applet
from .display.pdi import DisplayPDIApplet

from .audio.dac import AudioDACApplet
from .audio.yamaha_opx import AudioYamahaOPxApplet

from .video.rgb_input import VideoRGBInputApplet
from .video.vga_output import VGAOutputApplet
from .video.vga_terminal import VGATerminalApplet
from .video.ws2812_output import VideoWS2812OutputApplet

from .radio.nrf24l01 import RadioNRF24L01Applet
