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

This section documents Glasgow's embeddable APIs in a tutorial fashion.

.. toctree::

  getting-started-with-assemblies
  adding-an-applet
  adding-your-own-logic
  using-registers
  using-pins
  using-pipes

