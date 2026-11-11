``video-rgb-input``
===================

Capture row headers from a parallel RGB555 LCD bus, such as the Sharp LQ035Q7DH06.
Connect the five bits of each color in order from least to most significant, and connect
DCK to the pixel clock. DCK must remain high during vertical blanking.

For example, for a 160-column, 144-row LCD with a 960 µs vertical blanking interval::

    glasgow run video-rgb-input -V 3.3 \
        --r A0:4 --g A5:7,B0:1 --b B2:6 --dck B7 \
        --columns 160 --rows 144 --vblank 960e-6

Set the port voltage to match the LCD bus. The ``--vblank`` value is in seconds.

This applet is a preview; it prints ten frame/row headers and exits. It does not save or
display images. The capture skips the first pixel of each frame and resets its row and
column counters after DCK has remained high for 90% of the specified blanking interval.
Frame numbers wrap modulo 32. Row counts from 1 through 256 are supported.

CLI reference
-------------

.. _applet.video.rgb_input:

.. autoprogram:: glasgow.applet.video.rgb_input:VideoRGBInputApplet._get_argparser_for_sphinx("video-rgb-input")
    :prog: glasgow run video-rgb-input

API reference
-------------

.. module:: glasgow.applet.video.rgb_input

.. autoclass:: VideoRGBInputRow

.. autoclass:: VideoRGBInputInterface
