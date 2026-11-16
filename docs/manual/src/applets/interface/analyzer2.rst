``analyzer2``
=============

.. caution::

    To use this applet with Sigrok, you must use our fork of `libsigrok <https://codeberg.org/GlasgowEmbedded/libsigrok>`__ that includes the necessary drivers and bug fixes. (The :ref:`binary packages <install-binary>` include the correct build of libsigrok.)


CLI reference
-------------

.. _applet.interface.analyzer2:

.. autoprogram:: glasgow.applet.interface.analyzer2:AnalyzerApplet._get_argparser_for_sphinx("analyzer2")
    :prog: glasgow run analyzer2


API reference
-------------

.. role:: cmd(code)

.. module:: glasgow.applet.interface.analyzer2

.. autoclass:: DataFormat

.. autoclass:: DigitalFormat

.. autoenum:: DigitalTrigger

.. autoenum:: Marker

.. autoclass:: SampleBlock

.. autoexception:: AnalyzerError

.. autoclass:: AnalyzerInterface


Protocol reference
------------------

.. toctree::
    :hidden:

    analyzer2-protocol

The protocol used by this applet is :ref:`described in a separate document <analyzer2-protocol>`. If you've integrated this applet with a new application, please let us know!
