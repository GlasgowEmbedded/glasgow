"""An example of a Qt GUI that provides a simple, touchscreen-compatible factory flashing interface.

While the Glasgow Interface Explorer provides a very flexible CLI, it is rather too complicated
for simple, repetitive tasks like programming a QSPI memory. This example demonstrates how to
construct a task-specific GUI.
"""

import asyncio

from glasgow.support import logging
from glasgow.support.progress import QtWidgetsProgressImpl
from glasgow.hardware.assembly import HardwareAssembly
from glasgow.applet.memory._25q import Memory25QInterface
from glasgow.database.jedec import jedec_mfg_name_from_bytes
from glasgow.main import run_async_qtwidgets, setup_logging

from PySide6.QtWidgets import QDialog, QFileDialog

from ui_dialog import Ui_Memory25QDialog


logger = logging.getLogger(__name__)


class Memory25QDialog(QDialog, Ui_Memory25QDialog):
    def __init__(self):
        super().__init__()

        self.setupUi(self)
        QtWidgetsProgressImpl(self.progressBar, self.statusLabel).register()

        self.locateFileButton.clicked.connect(self.locateFile)
        self.jedecButton.clicked.connect(lambda: asyncio.ensure_future(self.jedec()))
        self.writeButton.clicked.connect(lambda: asyncio.ensure_future(self.write()))
        self.verifyButton.clicked.connect(lambda: asyncio.ensure_future(self.verify()))
        self.readButton.clicked.connect(lambda: asyncio.ensure_future(self.read()))

    def locateFile(self):
        fileName, _selectedFilter = QFileDialog.getSaveFileName(self,
            caption="Open Binary File", filter="Binary Files (*)",
            options=QFileDialog.Option.DontConfirmOverwrite)
        self.fileNameLineEdit.setText(fileName)

    def setEnabled(self, enabled: bool):
        self.fileNameLineEdit.setEnabled(enabled)
        self.locateFileButton.setEnabled(enabled)
        self.jedecButton.setEnabled(enabled)
        self.writeButton.setEnabled(enabled)
        self.verifyButton.setEnabled(enabled)
        self.readButton.setEnabled(enabled)

    async def withAssembly(self, operation):
        try:
            self.setEnabled(False)

            self.progressBar.setValue(0)
            self.statusLabel.setText("initializing...")

            assembly = await HardwareAssembly.find_device()
            assembly.use_voltage({"A": 3.3})
            mem_iface = Memory25QInterface(logger, assembly, cs="A0", sck="A1", io="A2:5")

            async with assembly:
                await mem_iface.qspi.clock.set_frequency(12_000_000)
                await mem_iface.initialize()
                await operation(mem_iface)

        except Exception as e:
            self.statusLabel.setText(f"error: {e}")

        finally:
            self.setEnabled(True)

    async def jedec(self):
        async def operation(mem_iface: Memory25QInterface):
            jedec_mfg_id, device_id = await mem_iface.jedec_id()
            jedec_mfg_name = jedec_mfg_name_from_bytes([jedec_mfg_id]) or "unknown"

            self.statusLabel.setText(
                f"vendor {jedec_mfg_name} ({jedec_mfg_id:02x}) device {device_id:04x}")

        await self.withAssembly(operation)

    async def write(self):
        async def operation(mem_iface: Memory25QInterface):
            with open(self.fileNameLineEdit.text(), "rb") as f:
                data = f.read()

            await mem_iface.write_data(0, data)
            self.statusLabel.setText("OK")

        await self.withAssembly(operation)

    async def verify(self):
        async def operation(mem_iface: Memory25QInterface):
            with open(self.fileNameLineEdit.text(), "rb") as f:
                golden = f.read()

            actual = await mem_iface.read_data(0, len(golden))
            if golden == actual:
                self.statusLabel.setText("OK")
            else:
                self.statusLabel.setText("Fail!")

        await self.withAssembly(operation)

    async def read(self):
        async def operation(mem_iface: Memory25QInterface):
            if size := mem_iface.memory_size:
                data = await mem_iface.read_data(0, size)
            else:
                raise ValueError("failed to identify memory size")

            with open(self.fileNameLineEdit.text(), "wb") as f:
                f.write(data)

        await self.withAssembly(operation)


@run_async_qtwidgets
async def main():
    setup_logging(level="DEBUG")

    Memory25QDialog().show()
