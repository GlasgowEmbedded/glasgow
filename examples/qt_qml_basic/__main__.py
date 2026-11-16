from importlib import resources

from PySide6.QtQml import QQmlApplicationEngine
from glasgow.main import run_async_qtqml, setup_logging
from glasgow.support import logging

logger = logging.getLogger(__name__)

@run_async_qtqml
async def main():
    setup_logging(level="DEBUG")

    engine = QQmlApplicationEngine()
    engine.loadData(resources.read_binary(__name__, "Main.qml"))
    return engine
