from .internal.selftest import SelfTestApplet
from .internal.benchmark import BenchmarkApplet

from .interface.uart import UARTApplet
from .interface.spi_master import SPIMasterApplet
from .interface.i2c_master import I2CMasterApplet
from .interface.jtag_pinout import JTAGPinoutApplet
from .interface.jtag_probe import JTAGProbeApplet
from .interface.jtag_svf import JTAGSVFApplet

from .memory._24x import Memory24xApplet
from .memory._25x import Memory25xApplet
from .memory.onfi import MemoryONFIApplet
from .memory.floppy import MemoryFloppyApplet

from .debug.arc import DebugARCApplet
from .debug.mips import DebugMIPSApplet
from .debug.arm_swd import DebugARMSWDApplet

from .program.avr.spi import ProgramAVRSPIApplet
from .program.ice40_flash import ProgramICE40FlashApplet
from .program.ice40_sram import ProgramICE40SRAMApplet
from .program.mec16xx import ProgramMEC16xxApplet
from .program.xc9500 import ProgramXC9500Applet

from .control.tps6598x import ControlTPS6598xApplet

from .sensor.bmp280 import SensorBMP280Applet

from .display.hd44780 import DisplayHD44780Applet
from .display.pdi import DisplayPDIApplet

from .audio.dac import AudioDACApplet
from .audio.yamaha_opl import AudioYamahaOPLApplet

from .video.rgb_input import VideoRGBInputApplet
from .video.vga_output import VGAOutputApplet
from .video.vga_terminal import VGATerminalApplet
