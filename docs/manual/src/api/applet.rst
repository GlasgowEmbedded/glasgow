``applet``
==========

.. module:: glasgow.applet

An applet is a class derived from :class:`GlasgowAppletV2`. The Glasgow CLI creates one instance per run, handing it an :class:`~glasgow.abstract.AbstractAssembly`, and drives it through these steps:

1. :py:`add_build_arguments` declares the command line options that select pins and supplies, typically with :meth:`GlasgowAppletArguments.add_ports_arguments`, and :py:`build` uses the parsed arguments to allocate gateware, ports, registers, and pipes on the assembly (see :ref:`api-abstract-ports`). Everything that goes into the bitstream must be decided here.
2. Once the bitstream is loaded, :py:`setup` configures the device, using the options from :py:`add_setup_arguments`.
3. :py:`run` implements the command line behavior of the applet, using the options from :py:`add_run_arguments`. An applet that does not implement :py:`run` can only be used in the REPL, where the interfaces that it exposes as attributes whose names end in ``iface`` are available.

Applets and the tools that accompany them are discovered through the entry point groups ``glasgow.applet`` and ``glasgow.applet.tool``, which :class:`GlasgowAppletMetadata` and :class:`GlasgowAppletToolMetadata` read.

Applets
-------

.. autoexception:: GlasgowAppletError
.. autoclass:: GlasgowAppletV2
.. autoclass:: GlasgowAppletArguments
.. autoclass:: GlasgowAppletTool
.. autoclass:: GlasgowAppletMetadata
.. autoclass:: GlasgowAppletToolMetadata

Testing applets
---------------

.. autoclass:: GlasgowAppletV2TestCase
.. autofunction:: synthesis_test
.. autofunction:: async_test
.. autofunction:: applet_v2_simulation_test
.. autofunction:: applet_v2_hardware_test
