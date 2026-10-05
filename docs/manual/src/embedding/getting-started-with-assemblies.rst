Getting started with Assemblies
-------------------------------

The core concept of the Glasgow embeddable API is the Assembly, accessible
through the ``glasgow.hardware.assembly.HardwareAssembly`` class
[#other_assemblies]_.  An Assembly represents a configuration of gateware
for a specific Glasgow, including all gateware necessary to interface with
the host software, and including all pipes and registers that the gateware
has access to.

Because each Assembly object is associated with a specific Glasgow, in order
to begin working with an Assembly, you will need to instantiate it with
reference to an attached device; you can use
``HardwareAssembly.find_device()`` to locate a device, and build an Assembly
based on it.  An Assembly has ``.start()`` and ``.stop()`` methods to
synthesize it and download it to the device, but for convenience, it also
implements the async context manager protocol to connect to the device. 
`The following skeleton of a program
<../_static/examples/assembly-skeleton.py>`_ will search for a Glasgow,
create an empty Assembly targetted to it, and then download it to the
attached Glasgow:

.. literalinclude:: ../_static/examples/assembly-skeleton.py
   :language: python

.. note::

    Most users that have `followed the recommended installation instructions
    <initial-setup>`__ will have Glasgow already installed via ``pipx``. 
    Usually, this is an important part of making Glasgow easy-to-install --
    but ``pipx`` is designed for standalone packages that are not meant to
    be imported!  Installing Glasgow outside of ``pipx`` in your own
    environment is outside of the scope of this document, but to run these
    samples, you might consider running inside of the Glasgow venv that
    ``pipx`` already set up for you.  For many users, doing so will take the
    form:

    .. code:: console

        $ ~/.local/pipx/venvs/glasgow/bin/python3 assembly-skeleton.py

Glasgow should respond:

.. code:: console

    DEBUG:asyncio:Using selector: EpollSelector
    DEBUG:glasgow.hardware.device:found revC3 device with serial C3-20240518T200308Z
    DEBUG:glasgow.hardware.toolchain:using toolchain 'builtin' (yosys 0.61.0.0.post1073, nextpnr-ice40 0.9.0.0.post686, icepack 0.9.0.0.post686)
    INFO:glasgow.hardware.device:generating bitstream ID ae08e17ee60fe32bc1165e0c59410d57
    DEBUG:glasgow.hardware.build_plan:bitstream ID ae08e17ee60fe32bc1165e0c59410d57 is not cached, executing build
    INFO:root:Glasgow is alive!

.. [#other_assemblies]

    There are other Assemblies in Glasgow; for instance, if you
    wish to develop gateware without hardware on your desk at all, you might
    consider a ``SimulationAssembly``.  All Assemblies derive from the
    ``AbstractAssembly`` base class, which is the type that you will most
    commonly find passed around in Glasgow's internals.  These types of
    Assemblies are out of scope for this document!
