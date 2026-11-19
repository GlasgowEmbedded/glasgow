``abstract``
============

.. automodule:: glasgow.abstract
   :no-members:

Building an applet interface
----------------------------

Allocate resources through the assembly while building an applet. Keep the returned register and pipe objects on the interface for use by asynchronous host methods. This allows the same interface code to run against hardware and simulation assemblies.

Declare the pins and supplies of an applet as a *ports class*, which :meth:`~glasgow.applet.GlasgowAppletArguments.add_ports_arguments` turns into command line options and :meth:`AbstractAssembly.add_ports` turns into Amaranth ports. See :ref:`api-abstract-ports` below.

For example, given a ports class, and a gateware component with an 8-bit command consumer, an 8-bit response producer, and a host-controlled enable signal::

    ports = assembly.add_ports(MyPorts, args)
    component = assembly.add_submodule(MyComponent(ports))
    enable = assembly.add_rw_register(component.enable)
    pipe = assembly.add_inout_pipe(component.responses, component.commands,
                                   in_flush=component.flush)

Host code can then enable the component and exchange bytes::

    await enable.set(1)
    await pipe.send(command)
    await pipe.flush()
    response = await pipe.recv(response_length)

Pipe directions use USB terminology: **IN** transfers bytes from gateware to the host; **OUT** transfers bytes from the host to gateware. Sending bytes may leave them buffered in the host, so flush commands before waiting for a response. The gateware's input flush signal separately forwards partial packets towards the host. Neither flush acknowledges that a command has finished executing. Command completion acknowledgements must be part of the applet's protocol.

.. _api-abstract-ports:

Declaring ports
---------------

A ports class is a dataclass that lists the pins of an applet and the supplies that power them. Pins are declared with :meth:`GlasgowPin.field` and annotated :py:`io.PortLike`, or :py:`io.PortLike | None` if they may be left unconnected. Supplies are declared with :meth:`GlasgowSupply.field` if the user chooses the voltage, or as a plain :py:`GlasgowSupply(voltage=3.3)` if it is fixed. Each pin names its supply with :py:`power=`, and the docstring after each field becomes its help text.

For example, an I²C bus with a configurable supply and an optional, active-low interrupt pin::

    @glasgow_ports
    class I2CPorts:
        supply: GlasgowSupply = GlasgowSupply.field(voltage_max=3.6)
        """bus power"""
        scl: io.PortLike = GlasgowPin.field(power=supply, default="A0")
        """I²C clock"""
        sda: io.PortLike = GlasgowPin.field(power=supply, default="A1")
        """I²C data"""
        int: io.PortLike | None = GlasgowPin.field(power=supply, invert=True, pull="high")
        """interrupt (active low)"""

An applet adds the options in :py:`add_build_arguments`, and creates the ports in :py:`build`::

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_ports_arguments(parser, I2CPorts)

    def build(self, args):
        with self.assembly.add_applet(self):
            ports = self.assembly.add_ports(I2CPorts, args)
            ...

This adds :py:`--scl`, :py:`--sda`, :py:`--int`, and :py:`-V/--voltage`. If an applet has more than one configurable supply, each option is named after its field instead, such as :py:`--i2c-voltage`. The voltage may be a number of volts, validated against the range declared for the supply, or a port to follow such as :py:`SA`, which mirrors the voltage sensed on port A (including the port's own sense input). If two applets in one assembly request different voltages for the same port, the assembly raises :exc:`~glasgow.abstract.VoltageConflictError`.

Interfaces take a ports object, annotated with the ports class they expect. An applet for a specific device can reuse the ports class of a generic interface directly, or build one from the pins it declares itself.

.. autofunction:: glasgow.abstract.glasgow_ports
.. autoexception:: glasgow.abstract.AssemblyBuildError
.. autoexception:: glasgow.abstract.VoltageConflictError
.. autoclass:: glasgow.abstract.GlasgowSupply

Physical connections and electrical configuration
-------------------------------------------------

.. autoenum:: glasgow.abstract.PullState
.. autoenum:: glasgow.abstract.GlasgowPort
.. autoclass:: glasgow.abstract.GlasgowVio
.. autoclass:: glasgow.abstract.GlasgowPin
.. autoclass:: glasgow.abstract.GlasgowAnalog
   :exclude-members: Nodes

.. autoenum:: glasgow.abstract.GlasgowAnalog.Nodes

Registers and clocks
--------------------

.. autoclass:: glasgow.abstract.AbstractRORegister
.. autoclass:: glasgow.abstract.AbstractRWRegister
.. autoclass:: glasgow.abstract.ClockDivisor
.. autoexception:: glasgow.abstract.ClockingError

Byte-stream pipes
-----------------

.. autoclass:: glasgow.abstract.AbstractInPipe
.. autoclass:: glasgow.abstract.AbstractOutPipe
.. autoclass:: glasgow.abstract.AbstractInOutPipe

Assembly resources
------------------

.. autoclass:: glasgow.abstract.DRAMOptions
.. autoclass:: glasgow.abstract.AbstractAssembly
