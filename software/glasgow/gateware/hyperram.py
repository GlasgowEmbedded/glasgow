# Ref: HyperBus™ Specification
# Ref: https://www.mouser.com/pdfdocs/cypress_hyperbus_specification.pdf
# Document Number: 001-99253
# Accession: ?

# This module is intended to be imported as `from glasgow.support import hyperbus` and then used
# as `hyperbus.PHYx1`, etc.

from amaranth import *
from amaranth.lib import enum, data, wiring
from amaranth.lib.wiring import Signature, In, Out


__all__ = ["PHYx1", "Sequencer"]


class StreamSignature(wiring.Signature):
    def __init__(self, payload_shape, *, reset=None):
        Shape.cast(payload_shape)
        super().__init__({
            "payload": Out(payload_shape, reset=reset),
            "valid": Out(1),
            "ready": In(1)
        })

    def create(self, *, path=None, src_loc_at=0):
        return StreamInterface(self, path=path, src_loc_at=1 + src_loc_at)


class StreamInterface(wiring.PureInterface):
    @property
    def p(self):
        return self.payload


class _IOBufferWithEn(wiring.Component):
    def __init__(self, pins, *, pin_type=C(0b1101_00, 6)):
        self.pins = pins
        self.pin_type = pin_type

        super().__init__(Signature({
            "en" : In(1),               # clock enable (for both input and output)
            "oe" : In(1),               # output enable
            "o"  : Out(len(self.pins)), # output
            "i"  : In(len(self.pins)),  # input
        }))

    def elaborate(self, platform):
        m = Module()
        for index, pin in enumerate(self.pins):
            m.submodules += Instance("SB_IO",
                p_PIN_TYPE=self.pin_type,
                i_INPUT_CLK=ClockSignal(),
                i_OUTPUT_CLK=ClockSignal(),
                i_CLOCK_ENABLE=self.en,
                i_OUTPUT_ENABLE=self.oe,
                # iCE40HX8K timing characteristics (85°C, 1.14 V):
                # - tCO =  5.41 ns (clock to output)
                # - tSU = -0.43 ns (clock to data setup)
                # - tH  =  2.38 ns (clock to data hold)
                # W957D8MFYA timing characteristics (85°C?, 1.8 V, 200 MHz):
                # - tDSV = 0..5 ns (CS# to RWDS valid)
                # - tCKD = 1..5 ns (CK to DQ valid)
                i_D_OUT_0=self.o[index],
                o_D_IN_0=self.i[index],
                io_PACKAGE_PIN=pin,
            )
        return m


class PHYMode(enum.Enum, shape=2):
    Select  = 0 # decodes CS# from `i.p.data`;
                # if `i.p.data != 0`, samples RWDS and writes to `o.p.data`
    CmdAddr = 1 # drives DQ from `i.p.data`
    Write   = 2 # drives DQ from `i.p.data` and RWDS from `i.p.mask`
    Read    = 3 # drives `o.p.data` from DQ when RWDS toggles


class PHYx1(wiring.Component):
    """Non-geared (one octet per cycle) HyperBus PHY.

    This PHY connects to a HyperBus memory device without deriving any new clocks or using any
    delay line primitives. The "x1" in the name refers to the lack of gearing; since HyperBus
    uses a DDR bus, this PHY runs the bus at one half the frequency of its clock domain,
    transferring 1 octet per cycle. This implementation allows DDR output buffers to be used
    to provide the required 90° phase offset for the memory clock, eliminating the need for a PLL.
    """

    Signature = wiring.Signature({
        "rst": Out(1),
        "o": Out(StreamSignature(data.StructLayout({
            "mode": PHYMode,
            "data": 16,
            "mask": 2,
            "last": 1
        }))),
        "i": In(StreamSignature(data.StructLayout({
            "data": 16,
            "last": 1 # o.last looped back
        })))
    })

    def __init__(self, resource):
        self.resource = resource

        super().__init__(self.Signature.flip())

    def elaborate(self, platform):
        pins = platform.request(*self.resource, xdr={
            "reset": 0,
            "ck_p":  2,
            "ck_n":  2,
        }, dir={
            "cs":    "-",
            "rwds":  "-",
            "dq":    "-",
        })

        m = Module()

        # RESET# is an unregistered output pin driven by `sync` domain reset. (It is not registered
        # to allow for configurations with asynchronous reset.)
        m.d.comb += pins.reset.o.eq(self.rst)

        # CK/CK# is a pseudo-differential pair (depending on HyperBus register configuration only
        # the positive polarity may be used), driven as source synchronous DDR output. This clock
        # idles low and toggles whenever the FSM transitions, at 90° phase offset referenced to
        # DQ[7:0]. The I/O buffer is configured as DDR to introduce the phase offset.
        m.d.comb += [
            pins.ck_p.o_clk.eq(ClockSignal()),
            pins.ck_n.o_clk.eq(ClockSignal()),
        ]

        # CS#[`cs_count`-1:0] are a set of output pins. They use the same type of IO buffer because
        # iCE40 has packing constraints on clock enables in adjacent SB_IO cells (same diffpair).
        # For the same reason the enable of CS# must be tied to that of RWDS, which requires this
        # awkward bit of logic to add a register not tied to RWDS enable.
        m.submodules.pins_cs_n = pins_cs_n = self.pins_cs_n = \
            _IOBufferWithEn(pins.cs, pin_type=C(0b0110_01, 6)) # Cat(PIN_INPUT, PIN_OUTPUT)
        pins_cs_o_n_reg = Signal.like(pins_cs_n.o, reset=~0)
        pins_cs_o       = Signal.like(pins_cs_n.o)
        pins_cs_o_en    = Signal()
        m.d.comb += pins_cs_n.o.eq(pins_cs_o_n_reg)
        with m.If(pins_cs_o_en):
            m.d.sync += pins_cs_o_n_reg.eq(~pins_cs_o)

        # RWDS is an input/output pin. It has three distinct functions:
        # - During command/address phase, RWDS is a memory output and FPGA input indicating whether
        #   the memory controller must introduce additional latency. It is essentially a strap with
        #   no particular timing relationship to other signals; it is enough to
        #   sample it somewhere during the C/A phase.
        # - During write transactions, RWDS is a memory input and FPGA output that is edge aligned
        #   with data output by the FPGA, masking off bytes that should not be written.
        # - During read transactions, RWDS is a memory output and FPGA input that is edge aligned
        #   with data output by the memory, indicating a pause in data transfer when the address
        #   crosses page boundaries.
        m.submodules.pins_rwds = pins_rwds = self.pins_rwds = _IOBufferWithEn(pins.rwds)
        m.d.comb += pins_cs_n.en.eq(pins_rwds.en) # oh, iCE40...
        pins_rwds_i_regl = Signal.like(pins_rwds.i)
        pins_rwds_i_regh = Signal.like(pins_rwds.i)

        # DQ[7:0] are a set of input/output pins. They are used for command, address, and data
        # transfer. When used as an output, DQ[7:0] changes state 90° before the transition
        # on CK/CK#; when used as an input, DQ[7:0] must be sampled 90° after the transition
        # on CK/CK#.
        m.submodules.pins_dq   = pins_dq   = self.pins_dq   = _IOBufferWithEn(pins.dq)
        pins_dq_i_regl   = Signal.like(pins_dq.i)
        pins_dq_i_regh   = Signal.like(pins_dq.i)

        with m.FSM():
            o_p_reg = Signal.like(self.o.p)
            clocked = Signal()
            m.d.comb += [
                # Idle.
                pins.ck_p.o0.eq(0),
                pins.ck_p.o1.eq(0),
                # Inverted.
                pins.ck_n.o0.eq(~pins.ck_p.o0),
                pins.ck_n.o1.eq(~pins.ck_p.o1),
            ]

            with m.State("Select/Deselect"):
                m.d.comb += [
                    pins_cs_o_en.eq(1),
                    # Release DQ and RWDS if the last operation was a write.
                    pins_dq.oe.eq(0),
                    pins_dq.en.eq(1),
                    pins_rwds.oe.eq(0),
                    pins_rwds.en.eq(1),
                ]
                m.d.sync += clocked.eq(0)
                with m.If(self.o.valid & (self.o.p.mode == PHYMode.Select)):
                    m.d.comb += self.o.ready.eq(1)
                    cs_decoded = Cat(self.o.p.data == n for n in range(1, len(pins_cs_o) + 1))
                    m.d.comb += pins_cs_o.eq(cs_decoded)
                    with m.If(cs_decoded != 0):
                        m.next = "Sample-Latency"

            with m.State("Sample-Latency"):
                m.d.comb += self.i.p.data.eq(pins_rwds.i)
                m.d.sync += clocked.eq(1)
                with m.If(~clocked):
                    # Capture RWDS at >=tDSV after CS# assertion.
                    m.d.comb += pins_rwds.en.eq(1)
                with m.Else():
                    m.d.comb += self.i.valid.eq(1)
                    with m.If(self.i.ready):
                        m.next = "Output"

            with m.State("Output"):
                with m.Switch(self.o.p.mode):
                    with m.Case(PHYMode.CmdAddr, PHYMode.Write):
                        m.d.comb += [
                            pins_dq.oe.eq(1),
                            pins_dq.o.eq(self.o.p.data[8:16]),
                            pins_rwds.oe.eq(self.o.p.mode == PHYMode.Write),
                            pins_rwds.o.eq(self.o.p.mask[1]),
                            self.o.ready.eq(1)
                        ]

                    with m.Case(PHYMode.Read):
                        # Capture DQa (D[15:8]) from previous CK negedge.
                        m.d.sync += [
                            pins_dq_i_regh.eq(pins_dq.i),
                            pins_rwds_i_regh.eq(pins_rwds.i),
                            # Don't accept command until we read a word with an RWDS strobe.
                        ]

                m.d.sync += o_p_reg.eq(self.o.p)
                m.d.sync += clocked.eq(0)
                with m.If(self.o.valid):
                    with m.If(self.o.p.mode == PHYMode.Select):
                        m.next = "Select/Deselect"
                    with m.Else():
                        m.d.comb += [
                            pins_rwds.en.eq(1),
                            pins_dq.en.eq(1),
                            pins.ck_p.o0.eq(0),
                            pins.ck_p.o1.eq(1),
                        ]
                        m.next = "Input"

            with m.State("Input"):
                with m.Switch(o_p_reg.mode):
                    with m.Case(PHYMode.CmdAddr, PHYMode.Write):
                        m.d.comb += [
                            pins_dq.oe.eq(1),
                            pins_dq.o.eq(o_p_reg.data[0:8]),
                            pins_rwds.oe.eq(o_p_reg.mode == PHYMode.Write),
                            pins_rwds.o.eq(o_p_reg.mask[0]),
                        ]
                        m.next = "Output"

                    with m.Case(PHYMode.Read):
                        # Capture DQb (D[8:0]) from previous CK posedge.
                        with m.If(~clocked):
                            m.d.sync += [
                                pins_dq_i_regl.eq(pins_dq.i),
                                pins_rwds_i_regl.eq(pins_rwds.i),
                            ]
                            m.d.comb += [
                                self.i.p.last.eq(o_p_reg.last),
                                self.i.p.data.eq(Cat(pins_dq.i,        pins_dq_i_regh)),
                                self.i.valid.eq( Cat(pins_rwds.i,      pins_rwds_i_regh) == 0b10),
                            ]
                        with m.Else():
                            m.d.comb += [
                                self.i.p.last.eq(o_p_reg.last),
                                self.i.p.data.eq(Cat(pins_dq_i_regl,   pins_dq_i_regh)),
                                self.i.valid.eq( Cat(pins_rwds_i_regl, pins_rwds_i_regh) == 0b10),
                            ]
                        # There are three different kinds of transitions this FSM may take here:
                        # 1. RWDS not H->L: repeat the command
                        # 2. RWDS is H->L, input ready: accept the command
                        # 3. RWDS is H->L, input not ready: stall and wait
                        # For transition (3), the `clocked` flag and `*_reg?` create a skid buffer.
                        m.d.comb += self.o.ready.eq(self.i.valid & self.i.ready)
                        with m.If(~self.i.valid | self.i.ready):
                            m.next = "Output"

                # The HyperBus specification forbids pausing or stopping the clock in the non-idle
                # state, so after the rising edge is generated, this state machine unconditionally
                # generates the falling edge. However, it may not be able to leave this state if
                # the input stream isn't ready.
                m.d.sync += clocked.eq(1)
                with m.If(~clocked):
                    m.d.comb += [
                        pins_rwds.en.eq(1),
                        pins_dq.en.eq(1),
                        pins.ck_p.o0.eq(1),
                        pins.ck_p.o1.eq(0),
                    ]

        return ResetInserter(self.rst)(m)


class Operation(enum.Enum, shape=1):
    """The R/W# field in the Command/Address information."""
    Write           = 0
    Read            = 1


class AddressSpace(enum.Enum, shape=1):
    """The AS field in the Command/Address information."""
    Memory          = 0
    Register        = 1


class BurstType(enum.Enum, shape=1):
    """The Burst Type field in the Command/Address information."""
    Wrapped         = 0
    Linear          = 1


class CommandAddress(data.Struct):
    """The Command/Address information at the beginning of a HyperBus transaction."""
    address_low     : 3
    _reserved       : 13
    address_high    : 29
    burst_type      : BurstType
    address_space   : AddressSpace
    operation       : Operation

    @classmethod
    def const(cls, init):
        if isinstance(init, dict) and "address" in init:
            init["address_low"]  = init["address"] & 0b111
            init["address_high"] = init["address"] >> 3
            del init["address"]
        return cls.as_shape().const(init)

    @property
    def address(self):
        return Cat(self.address_low, self.address_high)


class Sequencer(wiring.Component):
    def __init__(self, *, cs_count):
        super().__init__(Signature({
            "rst": In(1),
            "phy": Out(PHYx1.Signature),
            "ctl": In(StreamSignature(data.StructLayout({
                "select"    : range(cs_count + 1),
                "cmd_addr"  : CommandAddress,
                "latency"   : range(0, 16 + 1)
            }))),
            # The memory has to be "pumped" when reading; that is, for each `i`nput transfer to
            # happen, an `o`utput transfer has to happen first. Whether the input transfer will
            # be the last one (with the sequencer getting another command from `ctl`) or not is
            # determined by `o.last`. During reads, `o.data` and `o.mask` are not used.
            "o": In(StreamSignature(data.StructLayout({
                "data"  : 16,
                "mask"  : 2,
                "last"  : 1
            }))),
            "i": Out(StreamSignature(data.StructLayout({
                "data"  : 16,
                "last"  : 1
            })))
        }))

    def elaborate(self, platform):
        m = Module()
        phy = self.phy

        # The `rst` input resets both the sequencer, the PHY, and the RAM, which all contain bits
        # of state of the interface and must be reset synchronously.
        m.d.comb += phy.rst.eq(self.rst)

        # The cycle counter performs double duty: it is used to time the Command/Address phase as
        # well as the Latency phase after it. The counting of latency cycles starts from the third
        # cycle of the Command/Address phase, so the counter starts at -1 to simplify comparisons.
        cycle = Signal(range(-1, 16 << 1 + 1), reset=-1)

        # The latency must be doubled if RWDS is high after CS# assertion.
        latency = Signal.like(self.ctl.p.latency)

        # The command/address word is latched and shifted.
        cmd_addr = Signal(48)

        with m.FSM():
            with m.State("Select"):
                m.d.comb += [
                    phy.o.p.mode.eq(PHYMode.Select),
                    phy.o.p.data.eq(self.ctl.p.select),
                    phy.o.valid.eq(self.ctl.valid),
                ]
                m.d.sync += [
                    cycle.eq(cycle.reset),
                    latency.eq(self.ctl.p.latency),
                    cmd_addr.eq(self.ctl.p.cmd_addr),
                ]
                with m.If(phy.o.ready & self.ctl.valid):
                    m.next = "Latency"

            with m.State("Latency"):
                m.d.comb += phy.i.ready.eq(1)
                with m.If(phy.i.valid):
                    # If RWDS is asserted by the memory when it's selected, latency is doubled.
                    m.d.sync += latency.eq(Mux(phy.i.p.data[0], latency << 1, latency))
                    m.next = "Command/Address"

            with m.State("Command/Address"):
                m.d.comb += [
                    phy.o.p.mode.eq(PHYMode.CmdAddr),
                    phy.o.p.data.eq(cmd_addr[-16:]),
                    phy.o.valid.eq(1),
                ]
                with m.If(phy.o.ready):
                    m.d.sync += [
                        cycle.eq(cycle + 1),
                        cmd_addr.eq(Cat(C(0, 16), cmd_addr)),
                    ]
                    with m.If(cycle == 1):
                        m.d.comb += self.ctl.ready.eq(1) # Done processing the command.
                        with m.If(self.ctl.p.cmd_addr.operation == Operation.Read):
                            # Although reads have initial latency, it is not necessary to know it
                            # in advance because toggling of RWDS unambiguously delimits data.
                            # In addition, it is also not possible to know it in advance for reads
                            # from the register space because the default value for the initial
                            # latency value is not fixed, and there is no way to find it out other
                            # than by reading CR0.
                            m.next = "Latency-Read"
                        with m.Elif(self.ctl.p.cmd_addr.address_space == AddressSpace.Memory):
                            # Memory space writes generally have non-zero latency. Although
                            # the HyperBus specification allows memory space writes with zero
                            # latency, this is not generally used.
                            m.next = "Latency-Write"
                        with m.Else():
                            # Register space writes generally have zero latency. Although
                            # the HyperBus specification allows register space writes with non-zero
                            # latency, this is not generally used, and writes to CR0 must have zero
                            # latency or it would not be possible to set the initial latency value.
                            m.next = "Write"

            with m.State("Latency-Write"):
                m.d.comb += [
                    # "The master must drive RWDS to a valid Low before the end of the initial
                    #  latency to provide a data mask preamble period to the slave. This can be
                    #  done during the last cycle of the initial latency."
                    # This is achieved by using the write PHY mode (which drives RWDS) during that
                    # last cycle, and the command/address PHY mode (which does not) otherwise.
                    phy.o.p.mode.eq(Mux(cycle == latency, PHYMode.Write, PHYMode.CmdAddr)),
                    phy.o.valid.eq(1),
                ]
                with m.If(phy.o.ready):
                    m.d.sync += cycle.eq(cycle + 1)
                    with m.If(cycle == latency):
                        m.next = "Write"

            with m.State("Write"):
                m.d.comb += [
                    # Drive RWDS only if there was a turnaround time; do not drive it during
                    # a zero-latency write.
                    phy.o.p.mode.eq(Mux(latency != 0, PHYMode.Write, PHYMode.CmdAddr)),
                    phy.o.p.data.eq(self.o.p.data),
                    phy.o.p.mask.eq(self.o.p.mask),
                    phy.o.valid.eq(self.o.valid),
                    self.o.ready.eq(phy.o.ready),
                ]
                with m.If(self.o.valid & self.o.ready & self.o.p.last):
                    m.next = "Deselect"

            with m.State("Latency-Read"):
                m.d.comb += [
                    phy.o.p.mode.eq(PHYMode.CmdAddr),
                    phy.o.valid.eq(1),
                ]
                with m.If(phy.o.ready):
                    m.d.sync += cycle.eq(cycle + 1)
                    # In the Read state, words are pushed into the read stream whenever there is
                    # a 'high, low' transition on RWDS. The memory drives RWDS continuously for
                    # reads, but its function changes, and if the memory requests additional
                    # initial latency, there will be a 'high, low' transition at the beginning
                    # that does not indicate a data word being read.
                    with m.If(cycle == 3):
                        m.next = "Read"

            with m.State("Read"):
                 # `last` added and removed here
                m.d.comb += [
                    phy.o.p.mode.eq(PHYMode.Read),
                    phy.o.p.last.eq(self.o.p.last),
                    phy.o.valid.eq(self.o.valid),
                    self.o.ready.eq(phy.o.ready),
                ]
                m.d.comb += [
                    self.i.p.data.eq(phy.i.p.data),
                    self.i.p.last.eq(phy.i.p.last),
                    self.i.valid.eq(phy.i.valid),
                    phy.i.ready.eq(self.i.ready),
                ]
                with m.If(self.i.valid & self.i.ready & self.i.p.last):
                    m.next = "Deselect"

            with m.State("Deselect"):
                m.d.comb += [
                    phy.o.p.mode.eq(PHYMode.Select),
                    phy.o.valid.eq(1),
                ]
                with m.If(phy.o.ready):
                    m.next = "Select"

        return m
