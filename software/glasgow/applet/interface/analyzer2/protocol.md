<!-- This document uses the [MyST](https://myst-parser.readthedocs.io/) syntax, which extends Markdown with ReST constructs. It is integrated into the main documentation tree, but placed next to the applet for convenience. -->

(analyzer2-protocol)=
# Protocol description

This protocol is considered a versioned public API. Once included in the `main` branch, it will not be changed without updating the IDENTIFY command response, other than as necessary to fix specification bugs or to refine Uɴᴘʀᴇᴅɪᴄᴛᴀʙʟᴇ behavior.


## Glossary

- **Uɴᴘʀᴇᴅɪᴄᴛᴀʙʟᴇ**: Describes behavior that is not constrained by this specification. Frontends must avoid invoking such behavior.
- **Word**: 32-bit integer. Corresponds to the data path width and minimal addressable unit. Depending on data format, may contain multiple samples.
- **Block**: Multiple *words* containing sample data, terminated with a *trailer*. Samples are both internally processed and externally transmitted in blocks; during internal processing, blocks without an exceptional trailer may be merged to improve efficiency.
- **COBS**: [Consistent Overhead Byte Stuffing](https://www.stuartcheshire.org/papers/COBSforToN.pdf), a self-synchronizing transformation of byte streams used for efficiently inserting frame boundaries in streams of arbitrary binary data.
- **Trailer**: A single byte, placed last within a *COBS* frame containing a *block* of sample data. Indicates the exceptional nature of the last *word* within that block (whether it contains a trigger, overflow, or completion event). Zero if the last word is not exceptional.
- **Prolog**: Sample data returned before and immediately encompassing the trigger event. The last word of the prolog contains the sample that matched the trigger condition, or the sample that was being processed when a trigger was forced, which is indicated with the *trailer* of the last *block* of the prolog.
- **Epilog**: Sample data returned immediately after the *prolog*, and shortly after the trigger event. Can continue indefinitely if the transport conditions (bandwidth and latency) are sufficient.
- **FourCC**: [four-character code](https://en.wikipedia.org/wiki/FourCC), a sequence of four (wholly or in part printable-ASCII) bytes used as an identifier for data interchange.


## Overall framing

The protocol relies on an underlying reliable bidirectional byte stream transport, such as TCP or USB. (In the latter case, packet boundaries are don't care for this protocol.) It places no specific requirements on the transport nor has mandatory out-of-band components. When using TCP as the underlying transport, port 5555 may be used.

The protocol has a command-response structure, with the host sending commands. The host-to-device direction has no framing; the device-to-host direction uses COBS to distinguish between command responses and sample data.

```{important}
It is expected that a streaming COBS decoder such as [ccobs](https://github.com/Elizafox/ccobs) is used to process the device-to-host data; the protocol places no limit on the maximum size of a COBS frame.
```

The overall format of the device-to-host COBS frames is:

```
D>H: <COBS> index:u8 [data:u8*] </COBS>
```

The `index` denotes a *substream index*. Substream 0 contains command responses, substream 1 contains sample data.

Responses to commands take priority over sample data; when a response is required by the protocol and sample data is currently being streamed, the current block of sample data will be interrupted, the response will be sent, and the streaming of sample data will resume. Such interruption is transparent to the protocol, and no special handling is required: the interrupted block becomes a well-formed block with a *normal* trailer marker.


## Command sequences

```
H>D: type:u8 [arg:u32le]
D>H: <COBS> 0:u8 [ret:u32le] </COBS>
```

- `type[7]`: whether there is a return value
- `type[6]`: whether there is an argument
- `type[5]`: whether the command is a common or a trigger command
- `type[4..0]`: command code


## Sample data sequences

```
D>H: <COBS> 1:u8 [data:u32le]* trailer:u8 </COBS>
```

- `trailer[7..6]`: end marker of the data block:
  - `00`: *normal*, expect more samples in next block
  - `11`: *complete*, there will be no more samples until another trigger occurs
  - `10`: *trigger*, sub-word position described in bits 4..0
  - `01`: *overflow*, there are skipped samples *near* the last word
- `trailer[4..0]`: how far off into the last word is the trigger position, in bits (e.g. 16 for "second 14-bit sample"); integer multiple of data stride

Because the overflow condition is not discovered until a sample is forced into the full queue, it is difficult to precisely pinpoint the exact location of this condition. The second-to-last word of a data block marked with the overflow trailer still contains good samples; the samples contained within the last word have Uɴᴘʀᴇᴅɪᴄᴛᴀʙʟᴇ values.


## Metadata request sequences

```
H>D: type:u8 [arg:u32le]
D>H: <COBS> 1:u8 [data:u32le]* trailer:u8 </COBS>
D>H: <COBS> 2:u8 [metadata:u8]* </COBS>
```


## Common commands

These commands are a part of the base protocol and are independent of the selected trigger unit. They have types matching the mask `0bXX_0XXXXX`.


### `0b10_000000`: IDENTIFY

* `ret`: FourCC `0x30414c47`/`GLA0`

Identifies the protocol version and confirms the ability to communicate with the device.

```{important}
This command **must** be the first one sent by the frontend. Any future revision of the protocol will preserve the exact framing of (at least) this specific command and is guaranteed to respond to it with the framing described in this document and a FourCC distinct from `GLA0`. Any other host-to-device byte sequence causes Uɴᴘʀᴇᴅɪᴄᴛᴀʙʟᴇ effects in this case.
```

The response to this command is fixed for any given logic analyzer instance.


### `0b10_000001`: GET_CLK_FREQUENCY

* `ret` (`clk_frequency`): reference frequency in Hz (e.g. 48'000'000 for 48 MHz)

Returns the frequency of the reference clock of the sampling head. This value is used to convert a desired sample rate into a divisor value suitable for the SET_CLK_DIVISOR command.

The response to this command is fixed for any given logic analyzer instance.


### `0b01_000010`: SET_CLK_DIVISOR

* `arg[N..0]` (`clk_divisor`): clock divisor - 1 (e.g. 3 for DIV/4)

Configures the reload value for the clock divisor contained in the sampling head. This command invalidates buffered sample data similarly to the INTERRUPT command.

If the value of `clk_divisor` is too high or too low, it is clamped to the lowest or highest valid value for this logic analyzer instance. In conjunction with the GET_CLK_DIVISOR command, this behavior can be used to probe the available range of divisor values.

On startup, `clk_divisor` is Uɴᴘʀᴇᴅɪᴄᴛᴀʙʟᴇ.


### `0b10_000010`: GET_CLK_DIVISOR

* `arg[N..0]` (`clk_divisor`): clock divisor - 1

Returns the configured clock divisor reload value. Since the exact width (`N`) of the divisor register is unspecified, this command should be used to confirm that the desired clock divisor value is feasible.


### `0b10_000011`: GET_BUFFER_SIZE

* `ret[29..0]` (`buffer_size`): capture buffer size in units of words (e.g. 0x40000 for 1 MB)

Returns the maximum amount of data that can be stored within the device's onboard RAM. *This is not a limit on sampling length.* Instead, this value can be used to make some important inferences:

- If the sum of the prolog and epilog sizes is less than or equal to the capture buffer size, then the capture is guaranteed to complete unless it exceeds the RAM write bandwidth. If it is greater than the capture buffer size, then an overflow may be caused by unfavorable USB bandwidth or latency.
- The prolog size must be strictly less than the capture buffer size; if configured otherwise, the effect is Uɴᴘʀᴇᴅɪᴄᴛᴀʙʟᴇ. (There are no restrictions on the epilog size.)

The response to this command is fixed for any given logic analyzer instance.


### `0b01_000100`: SET_PROLOG_SIZE

* `arg[29..0]` (`prolog_size`): prolog size in units of words

Configures the upper bound on the amount of pre-trigger capture data that will be sent. Less data than `prolog_size` specifies may be sent if the trigger occurred too soon after a pipeline flush and the requested amount of data has not been sampled yet.

At least one word of prolog must be transmitted, otherwise the data and offset of the *trigger* event cannot be communicated. If `prolog_size` is 0, the command acts as if `prolog_size` was set to 1.

On startup, `prolog_size` is 1.


### `0b01_000101`: SET_EPILOG_SIZE

* `arg[0..29]` (`epilog_size`): epilog size in units of words
* `arg[31]` (`streaming`): whether to capture continuously instead

Configures the exact amount of post-trigger capture data that will be sent. If `streaming` is 1, then `epilog_size` is disregarded and samples are streamed continuously until an overflow occurs or an INTERRUPT command is received.

At least one word of epilog must be transmitted, otherwise the *complete* event cannot be communicated. If `streaming` is 0 and `epilog_size` is 0, the command acts as `epilog_size` it was set to 1.

On startup, `streaming` is 1.


### `0b10_000110`: GET_DATA_FORMAT

* `ret` (`data_format`): FourCC describing sample data format

Describes the meaning of the sample data words.

The response to this command is fixed for any given logic analyzer instance.

Unrecognized data formats must be reported by the frontend as an error unless there is an option to save the raw capture data for analysis with a different tool.


#### Digital samples: FourCC `0x4944xxxx`/`DIxx`

* `data_format[0..4]` (`width`): how many bits are valid for each sample
* `data_format[8..12]` (`stride`): how many bits to advance to get to the next sample (power-of-2, 1 to 32 inclusive)

Describes the placement of digital samples within each word. Each sample starts on a power-of-2 bit index (a multiple of `stride`) and continuously occupies `width` bits. Therefore, a single word may contain 1, 2, 4, 8, 16, or 32 digital samples depending on the `width`.

First captured sample is placed in the least significant bits of the data word.


#### Mixed analog/digital samples: FourCC `0x4e41xxxx`/`ANxx`

This is a planned data format that hasn't been prototyped yet.


### `0b01_010000`: SET_TRIGGER

* `arg` (`trigger`): FourCC of requested trigger block

When `arg` designates a valid trigger block, selects (enables) and resets this trigger block. Any other trigger blocks are disabled, and all commands matching the `0bXX_1XXXXX` mask are routed to the selected trigger block. When `arg` does not designate a valid trigger block, does nothing.

On startup, `trigger` is Uɴᴘʀᴇᴅɪᴄᴛᴀʙʟᴇ.

Unrecognized trigger blocks must be reported by the frontend as an error unless there is an option to enter a custo configuration of trigger registers as a raw sequence of 32-bit trigger commands.

Commands whose types match the mask `0bXX_1XXXXX` belong to the selected trigger unit. Many more types of triggers can exist than can be anticipated by the authors of this specification; this extension point allows the end user to customize the trigger conditions for any particular domain.


### `0b10_010000`: GET_TRIGGER

* `ret` (`trigger`): FourCC of the selected trigger block

Identifies the currently selected trigger block. Can be used to confirm success of the SET_TRIGGER command, or to avoid resetting a trigger block that is already selected.


### `0b10_010001`: GET_METADATA

* `ret` (`metadata_format`): FourCC of the metadata format

Sends metadata as an uninterrupted frame in substream 2 after the normal command response.


#### No metadata: FourCC `0x00000000`

No metadata available. As a special case, there will be no substream 2 frame after this response.


#### Channel name list: FourCC `NAME`/`0x454d414e`

List of UTF-8 encoded channel names separated by NUL bytes. For example, the following hex dump corresponds to metadata for a 4-channel logic analyzer with channels named `CS#`, `CLK`, `COPI`, `CIPO`:

```
00000000  43 53 23 00 43 4c 4b 00  43 4f 50 49 00 43 49 50  |CS#.CLK.COPI.CIP|
00000010  4f                                                |O|
00000011
```


### `0b11_011111`: SYNCHRONIZE

* `arg`: any value
* `ret`: `arg`

Bounces the argument back. Can be used to re-establish command/response synchronization after an exceptional condition such as buffer overflow somewhere between the host and the device (not to be confused with an overflow condition during sampling).

To avoid ambiguity, the argument should be a high-entropy value; at least, two consecutive invocations should not have the same argument.


### `0b00_000000`: ARM_TRIGGER

Enables the trigger unit. Once the trigger condition is fulfilled, the trigger unit is disabled, and sample data is returned as configured by `prolog_size`, `epilog_size`, and `streaming`.


### `0b00_000001`: FORCE_TRIGGER

Forces a trigger condition to occur. Immediately after receiving this command, the trigger unit is disabled, and sample data is returned as with the ARM_TRIGGER command.


### `0b00_000010`: DISARM_TRIGGER

Disables the trigger unit.


### `0b00_000011`: INTERRUPT

Stops any capture in progress, disables the trigger unit, and discards any accumulated capture data that would otherwise be returned as a part of the prolog of the following trigger event.


## Basic trigger: FourCC `0x49534142`/`BASI`

Basic trigger module. Generates a trigger match if any of the per-bit conditions are satisfied. The possible per-bit conditions are: rising edge, falling edge, high level, low level.

It is possible to modify the trigger condition after issuing the ARM_TRIGGER command. The updated condition takes effect immediately.


### `0b01_100000`: TRIG_BASIC_SET_ACTIVE

* `arg[n]`: whether to match on channel `n`


### `0b01_100001`: TRIG_BASIC_SET_LEVEL

* `arg[n]`: whether channel `n` is compared by level (1) or by edge (0)


### `0b01_100010`: TRIG_BASIC_SET_VALUE

* `arg[n]` (if channel `n` is compared by edge): whether to match channel `n` on negative (0) or positive (1) edge
* `arg[n]` (if channel `n` is compared by level): whether to match channel `n` on low (0) or high (1) level


### `0b01_100011`: TRIG_BASIC_SET_ANYEDGE

* `arg[n]` (if channel `n` is compared by edge): whether to match channel `n` on both positive and negative edges (1) or the edge specified by TRIG_BASIC_SET_VALUE (0)
* `arg[n]` (if channel `n` is compared by level): Uɴᴘʀᴇᴅɪᴄᴛᴀʙʟᴇ behavior
