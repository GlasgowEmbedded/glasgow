``audio-yamaha-opx``
====================

CLI reference
includes an example script and the ``--filter-script`` command filter interface.

To serve the bundled web player on a local endpoint::

    glasgow run audio-yamaha-opx -V 3.3 --device OPL2 web localhost:8080

The web player accepts uploaded VGM/VGZ files. Fetching files from submitted URLs
requires explicitly enabling ``--allow-urls``.

CLI reference
-------------

.. _applet.audio.yamaha_opx:

.. autoprogram:: glasgow.applet.audio.yamaha_opx:AudioYamahaOPxApplet._get_argparser_for_sphinx("audio-yamaha-opx")
    :prog: glasgow run audio-yamaha-opx


API reference
-------------

.. module:: glasgow.applet.audio.yamaha_opx

.. autoclass:: YamahaOPxInterface

.. autoclass:: YamahaOPLInterface

.. autoclass:: YamahaOPL2Interface

.. autoclass:: YamahaOPL3Interface

.. autoclass:: YamahaOPMInterface

.. autoclass:: YamahaOPxCommandFilter
