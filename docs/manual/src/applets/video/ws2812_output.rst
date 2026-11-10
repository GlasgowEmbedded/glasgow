``video-ws2812-output``
=======================

Drive one or more parallel WS2812(B) LED strings from a TCP or Unix socket::

    glasgow run video-ws2812-output --voltage 3.3 --out A0:3 --count 60 tcp::1234

Provide power for the LEDs separately and connect their ground to Glasgow ground.
Choose an I/O voltage compatible with the LED data inputs.

The socket accepts raw frames without headers. Each frame contains ``--count`` pixels
per output pin. Pixels are interleaved across strings in pin order: pixel 0 for each
string, then pixel 1 for each string, and so on. All strings must have the same length.

``--pix-fmt`` selects the input channels and their order on the wire:

* ``RGB-BRG``: RGB input, transmitted in GRB order (the default for WS2812B).
* ``RGB-xBRG``: RGB input, transmitted in GRB order followed by a zero white channel.
* ``RGBW-WBRG``: RGBW input, transmitted in GRBW order.

Format names describe the packed gateware word from least to most significant byte;
transmission starts with the most significant bit. Channel values are unsigned bytes.
A frame is therefore ``number of strings × count × input channels`` bytes long.
Socket writes may split frames or contain several frames. An incomplete frame is
discarded when the client disconnects; the applet then accepts another connection.

``--buffer`` controls the number of frames buffered in each of the socket receive
queue and USB output pipe (default: 16). The FPGA inserts a reset interval of at
least 300 µs after each frame.

CLI reference
-------------

.. _applet.video.ws2812_output:

.. autoprogram:: glasgow.applet.video.ws2812_output:VideoWS2812OutputApplet._get_argparser_for_sphinx("video-ws2812-output")
    :prog: glasgow run video-ws2812-output

API reference
-------------

.. module:: glasgow.applet.video.ws2812_output

.. autoclass:: WS2812OutputInterface
