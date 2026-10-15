# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'dialogrzLvaw.ui'
##
## Created by: Qt User Interface Compiler version 6.8.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
    QLayout, QLineEdit, QProgressBar, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget)

class Ui_Memory25QDialog(object):
    def setupUi(self, Memory25QDialog):
        if not Memory25QDialog.objectName():
            Memory25QDialog.setObjectName(u"Memory25QDialog")
        Memory25QDialog.resize(764, 150)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(Memory25QDialog.sizePolicy().hasHeightForWidth())
        Memory25QDialog.setSizePolicy(sizePolicy)
        Memory25QDialog.setMinimumSize(QSize(0, 150))
        Memory25QDialog.setModal(True)
        self.verticalLayout = QVBoxLayout(Memory25QDialog)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.horizontalLayout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.fileNameLineEdit = QLineEdit(Memory25QDialog)
        self.fileNameLineEdit.setObjectName(u"fileNameLineEdit")
        self.fileNameLineEdit.setMinimumSize(QSize(300, 0))

        self.horizontalLayout.addWidget(self.fileNameLineEdit)

        self.locateFileButton = QPushButton(Memory25QDialog)
        self.locateFileButton.setObjectName(u"locateFileButton")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.locateFileButton.sizePolicy().hasHeightForWidth())
        self.locateFileButton.setSizePolicy(sizePolicy1)

        self.horizontalLayout.addWidget(self.locateFileButton)

        self.jedecButton = QPushButton(Memory25QDialog)
        self.jedecButton.setObjectName(u"jedecButton")
        sizePolicy1.setHeightForWidth(self.jedecButton.sizePolicy().hasHeightForWidth())
        self.jedecButton.setSizePolicy(sizePolicy1)

        self.horizontalLayout.addWidget(self.jedecButton)

        self.writeButton = QPushButton(Memory25QDialog)
        self.writeButton.setObjectName(u"writeButton")
        sizePolicy1.setHeightForWidth(self.writeButton.sizePolicy().hasHeightForWidth())
        self.writeButton.setSizePolicy(sizePolicy1)

        self.horizontalLayout.addWidget(self.writeButton)

        self.verifyButton = QPushButton(Memory25QDialog)
        self.verifyButton.setObjectName(u"verifyButton")
        sizePolicy1.setHeightForWidth(self.verifyButton.sizePolicy().hasHeightForWidth())
        self.verifyButton.setSizePolicy(sizePolicy1)

        self.horizontalLayout.addWidget(self.verifyButton)

        self.readButton = QPushButton(Memory25QDialog)
        self.readButton.setObjectName(u"readButton")
        sizePolicy1.setHeightForWidth(self.readButton.sizePolicy().hasHeightForWidth())
        self.readButton.setSizePolicy(sizePolicy1)

        self.horizontalLayout.addWidget(self.readButton)


        self.verticalLayout.addLayout(self.horizontalLayout)

        self.progressBar = QProgressBar(Memory25QDialog)
        self.progressBar.setObjectName(u"progressBar")
        self.progressBar.setValue(0)
        self.progressBar.setTextVisible(False)
        self.progressBar.setInvertedAppearance(False)

        self.verticalLayout.addWidget(self.progressBar)

        self.statusLabel = QLabel(Memory25QDialog)
        self.statusLabel.setObjectName(u"statusLabel")
        self.statusLabel.setScaledContents(False)
        self.statusLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.verticalLayout.addWidget(self.statusLabel)


        self.retranslateUi(Memory25QDialog)

        self.jedecButton.setDefault(True)


        QMetaObject.connectSlotsByName(Memory25QDialog)
    # setupUi

    def retranslateUi(self, Memory25QDialog):
        Memory25QDialog.setWindowTitle(QCoreApplication.translate("Memory25QDialog", u"Glasgow Flash Burning Tool", None))
        self.locateFileButton.setText(QCoreApplication.translate("Memory25QDialog", u"...", None))
        self.jedecButton.setText(QCoreApplication.translate("Memory25QDialog", u"ID", None))
        self.writeButton.setText(QCoreApplication.translate("Memory25QDialog", u"Write", None))
        self.verifyButton.setText(QCoreApplication.translate("Memory25QDialog", u"Verify", None))
        self.readButton.setText(QCoreApplication.translate("Memory25QDialog", u"Read", None))
        self.statusLabel.setText(QCoreApplication.translate("Memory25QDialog", u"ready", None))
    # retranslateUi

