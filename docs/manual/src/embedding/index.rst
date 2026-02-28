Embedding Glasgow
=================

For some applications, it may be either inconvenient or inappropriate to use
the Glasgow applet interface.  For instance, you may wish to build a class
of interface for Glasgow that will not ever end up in Glasgow upstream (and
therefore should not be written inside of the Glasgow repository); you may
wish to control Glasgow in another program's main loop; or you may wish to
write a quick one-off experiment without the full infrastructure of Glasgow. 

Such applications may prefer to use Glasgow's embeddable APIs, which provide
access to directly find and instantiate Glasgow hardware, to build gateware
and host-side interfaces, and to load and run the generated programs on
Glasgow hardware.  The embeddable APIs are designed to provide a similar
level of abstraction as the Glasgow applet interface (the embeddable API is
responsible for generating and loading bitstreams, and providing physical
communications with Glasgow), but control flow is owned by the host
application; Glasgow's embeddable APIs run in an ordinary Python `asyncio`
framework.

.. caution::

    Glasgow's embeddable APIs are an implementation artifact of the existing
    applet architecture, which is the only committed interface for Glasgow. 
    All applets inside the Glasgow repository will be maintained and pushed
    forward when internal APIs change -- but if you develop against
    Glasgow's embeddable APIs, they may change underneath you in future
    versions of Glasgow!

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
based on it.  An Assembly has `.start()` and `.stop()` methods to synthesize
it and download it to the device, but for convenience, it also implements
the async context manager protocol to connect to the device.  The following
skeleton of a program will search for a Glasgow, create an empty Assembly
targetted to it, and then download it to the attached Glasgow:

.. code:: python

    # assembly-skeleton.py
    # XXX: I have distilled but not actually tested this snippet on hardware yet

    import asyncio
    import logging

    from glasgow.hardware.assembly import HardwareAssembly

    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger()

    async def main():
        assembly = await HardwareAssembly.find_device()
        async with assembly:
            logger.info("Glasgow is alive!")
            await asyncio.sleep(5)

    if __name__ == "__main__":
        asyncio.run(main())

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

Adding an applet to an Assembly
-------------------------------

Putting your own logic into an Assembly
---------------------------------------

Using registers to connect to logic
-----------------------------------

Connecting to pins
------------------

Using pipes to transfer data
----------------------------

.. [#other_assemblies]

    There are other Assemblies in Glasgow; for instance, if you
    wish to develop gateware without hardware on your desk at all, you might
    consider a ``SimulationAssembly``.  All Assemblies derive from the
    ``AbstractAssembly`` base class, which is the type that you will most
    commonly find passed around in Glasgow's internals.  These types of
    Assemblies are out of scope for this document!
