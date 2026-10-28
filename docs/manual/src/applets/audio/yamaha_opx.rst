``audio-yamaha-opx``
====================

The CLI reference includes an example script for generating synthesizer commands.

To serve the bundled web player on a local endpoint::

    glasgow run audio-yamaha-opx -V 3.3 --device OPL2 web localhost:8080

The web player accepts uploaded VGM/VGZ files. Fetching files from submitted URLs
requires explicitly enabling ``--allow-urls``.

Filter scripts
--------------

Commands submitted to the synthesizer can be preprocessed with a Python script, e.g.
for glitching, using the ``--filter-script`` option. The script must define a
``CommandFilter`` subclass of :class:`~glasgow.applet.audio.yamaha_opx.YamahaOPxCommandFilter`,
which is available in the script's global namespace:

.. code-block:: python

    class CommandFilter(YamahaOPxCommandFilter):
        async def write_register(self, address, data):
            ...
            return (address, data)


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
