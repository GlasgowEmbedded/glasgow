import asyncio
import logging
import struct
from amaranth import *
from amaranth.lib import enum, data, wiring, fifo
from amaranth.lib.wiring import Signature, In, Out

from glasgow.gateware import hyperram


class HyperRAMSequencerTestbench(wiring.Component):
    rst     : In(1)
    cmd_addr: In(hyperram.CommandAddress)
    latency : In(range(3, 17))
    length  : In(24)
    trigger : In(1)  # posedge-triggered

    def __init__(self, *, out_fifo, in_fifo):
        self.out_fifo = out_fifo
        self.in_fifo  = in_fifo

        super().__init__()

    def elaborate(self, platform):
        platform.add_ram_pak_resources()

        m = Module()

        m.submodules.phy = phy = hyperram.PHYx1(resource=("hyperram", 0))
        m.submodules.seq = seq = hyperram.Sequencer(cs_count=1)
        wiring.connect(m, seq.phy, phy)

        m.d.comb += [
            seq.rst.eq(self.rst),
            seq.ctl.payload.select.eq(1),
            seq.ctl.payload.cmd_addr.eq(self.cmd_addr),
            seq.ctl.payload.latency.eq(self.latency),
        ]

        trigger_reg = Signal.like(self.trigger)
        m.d.sync += trigger_reg.eq(self.trigger)
        with m.If(~trigger_reg & self.trigger):
            m.d.sync += seq.ctl.valid.eq(1)
        with m.Elif(seq.ctl.ready):
            m.d.sync += seq.ctl.valid.eq(0)

        with m.FSM(name="output_fsm"):
            r_data_reg = Signal.like(self.out_fifo.r_data)
            remain = Signal.like(self.length)

            with m.State("Idle"):
                m.d.sync += remain.eq(self.length)
                with m.If(seq.ctl.valid & seq.ctl.ready):
                    with m.If(seq.ctl.payload.cmd_addr.operation == hyperram.Operation.Read):
                        m.next = "Read"
                    with m.Else():
                        m.next = "Write-MSB"

            with m.State("Read"):
                m.d.comb += [
                    seq.o.payload.last.eq(remain == 1),
                    seq.o.valid.eq(1),
                ]
                with m.If(seq.o.ready):
                    with m.If(remain == 1):
                        m.next = "Idle"
                    with m.Else():
                        m.d.sync += remain.eq(remain - 1)

            with m.State("Write-MSB"):
                m.d.sync += [
                    r_data_reg.eq(self.out_fifo.r_data)
                ]
                m.d.comb += [
                    self.out_fifo.r_en.eq(1),
                ]
                with m.If(self.out_fifo.r_rdy & self.out_fifo.r_en):
                    m.next = "Write-LSB"

            with m.State("Write-LSB"):
                m.d.comb += [
                    seq.o.payload.data[8:].eq(r_data_reg),
                    seq.o.payload.data[:8].eq(self.out_fifo.r_data),
                    seq.o.payload.last.eq(remain == 1),
                    seq.o.valid.eq(self.out_fifo.r_rdy),
                    self.out_fifo.r_en.eq(seq.o.ready),
                ]
                with m.If(self.out_fifo.r_rdy & self.out_fifo.r_en):
                    with m.If(remain == 1):
                        m.next = "Idle"
                    with m.Else():
                        m.d.sync += remain.eq(remain - 1)
                        m.next = "Write-MSB"

        with m.FSM(name="input_fsm"):
            with m.State("Read-MSB"):
                m.d.comb += [
                    self.in_fifo.w_data.eq(seq.i.p.data[8:]),
                    self.in_fifo.w_en.eq(seq.i.valid),
                    seq.i.ready.eq(0),
                ]
                with m.If(self.in_fifo.w_rdy & self.in_fifo.w_en):
                    m.d.sync += self.in_fifo.flush.eq(0)
                    m.next = "Read-LSB"

            with m.State("Read-LSB"):
                m.d.comb += [
                    self.in_fifo.w_data.eq(seq.i.p.data[:8]),
                    self.in_fifo.w_en.eq(1),
                    seq.i.ready.eq(self.in_fifo.w_rdy),
                ]
                with m.If(self.in_fifo.w_rdy & self.in_fifo.w_en):
                    m.d.sync += self.in_fifo.flush.eq(seq.i.p.last)
                    m.next = "Read-MSB"

        return m


async def main():
    from glasgow.target.hardware import GlasgowHardwareTarget
    from glasgow.device.hardware import GlasgowHardwareDevice

    # logging.getLogger().setLevel(logging.TRACE)
    logging.getLogger().addHandler(loggingHandler := logging.StreamHandler())
    loggingHandler.setFormatter(
        logging.Formatter(style="{", fmt="{levelname[0]:s}: {name:s}: {message:s}"))

    device = GlasgowHardwareDevice()
    target = GlasgowHardwareTarget(revision=device.revision)
    tb_rst, tb_rst_addr = target.registers.add_rw(1, reset=1)
    target.add_submodule(testbench := ResetInserter(tb_rst)(
        HyperRAMSequencerTestbench(
            out_fifo=target.fx2_crossbar.get_out_fifo(0, reset=tb_rst),
            in_fifo=target.fx2_crossbar.get_in_fifo(0, reset=tb_rst))))
    ram_rst_addr  = target.registers.add_existing_rw(testbench.rst)
    cmd_addr_addr = target.registers.add_existing_rw(testbench.cmd_addr)
    latency_addr  = target.registers.add_existing_rw(testbench.latency)
    length_addr   = target.registers.add_existing_rw(testbench.length)
    trigger_addr  = target.registers.add_existing_rw(testbench.trigger)
    await device.download_target(target.build_plan(), reload=True)

    print("Running...")
    device.usb_handle.setConfiguration(1)
    device.usb_handle.claimInterface(0)
    device.usb_handle.setInterfaceAltSetting(0, 1)
    await device.write_register(tb_rst_addr, 0)

    await device.write_register(ram_rst_addr, 1)
    await device.write_register(ram_rst_addr, 0)

    async def prepare(addr_space, operation, latency, offset, length):
        await device.write_register(cmd_addr_addr, hyperram.CommandAddress.const({
            "operation": operation,
            "burst_type": hyperram.BurstType.Linear,
            "address_space": addr_space,
            "address": offset,
        }).as_value().value, width=6)
        await device.write_register(latency_addr, latency)
        await device.write_register(length_addr, length, width=3)
        await device.write_register(trigger_addr, 0)
        await device.write_register(trigger_addr, 1)

    def display(addr_space, operation, offset, data):
        for o, n in enumerate(data):
            op = (" <=" if operation == hyperram.Operation.Write else "=>")
            if addr_space == hyperram.AddressSpace.Register:
                print(f"R[{offset+o:#08x}] {op} {n:04x}")
            if addr_space == hyperram.AddressSpace.Memory:
                print(f"M[{offset+o:#010x}] {op} {n:04x}")

    async def read(*, addr_space, operation, offset, length):
        await prepare(addr_space, hyperram.Operation.Read, 0, offset, length)
        data = b""
        while len(data) < length * 2:
            data += await device.bulk_read(0x86, 65536)
        data = [n for (n,) in struct.iter_unpack(">H", data[:length * 2])]
        # display(addr_space, operation, offset, data)
        return data

    async def write(*, addr_space, operation, latency, offset, data):
        # display(addr_space, operation, offset, data)
        await prepare(addr_space, hyperram.Operation.Write, latency, offset, len(data))
        data = b"".join(struct.pack(">H", n) for n in data)
        await device.bulk_write(0x02, data)

    async def read_reg(offset):
        value, = await read(
            addr_space=hyperram.AddressSpace.Register,
            operation=hyperram.Operation.Read,
            offset=offset,
            length=1
        )
        return value

    async def write_reg(offset, value):
        await write(
            addr_space=hyperram.AddressSpace.Register,
            operation=hyperram.Operation.Write,
            latency=0,
            offset=offset,
            data=[value]
        )

    async def read_mem(offset, length):
        return await read(
            addr_space=hyperram.AddressSpace.Memory,
            operation=hyperram.Operation.Read,
            offset=offset,
            length=length
        )

    async def write_mem(offset, data, *, latency):
        await write(
            addr_space=hyperram.AddressSpace.Memory,
            operation=hyperram.Operation.Write,
            latency=latency,
            offset=offset,
            data=data
        )

    assert await read_reg(0x000000) == 0x0c86

    # 128 Mb flash, one char per word, but the flash is 2-die and doesn't wrap from 0 to 1
    bee_list = list(BEE_MOVIE) * (64*1048576//16//len(BEE_MOVIE))
    print(f"writing {len(bee_list)*2} bytes")
    await write_mem(0, bee_list, latency=7)
    print(f"reading {len(bee_list)*2} bytes")
    readback = await read_mem(0, len(bee_list))
    if readback != bee_list:
        with open("gold.bin", "wb") as f: f.write(b"".join(struct.pack(">H", n) for n in bee_list))
        with open("read.bin", "wb") as f: f.write(b"".join(struct.pack(">H", n) for n in readback))
    assert readback == bee_list

    # await read_reg(0x000000) # ID0 == 0c86
    # await read_reg(0x000001) # ID1 == 0001

    # await write_mem(0x00000000, [0x0000, 0x0000, 0x0000], latency=7)
    # assert await read_mem( 0x00000000, 3) == [0x0000, 0x0000, 0x0000]
    # await write_mem(0x00000000, [0x1234, 0x5678, 0xabcd], latency=7)
    # assert await read_mem( 0x00000000, 3) == [0x1234, 0x5678, 0xabcd]

    # await read_reg(0x000800) # CR0 == 8f2f
    # await write_reg(0x000800, 0x8f1f)
    # await read_reg(0x000800)
    # await write_reg(0x400800, 0x8f1f)
    # await read_reg(0x400800)

    # await read_reg(0x000801) # CR1 == ffc1

    # await read_mem(0x00000000, 1)
    # await read_mem(0x00000001, 1)
    # await write_mem(0x00000000, [0xaabb], latency=6)
    # await write_mem(0x00000001, [0xccdd], latency=6)
    # await read_mem(0x00000000, 1)
    # await read_mem(0x00000001, 1)
    # await write_mem(0x00000000, [0], latency=6)
    # await write_mem(0x00000001, [0], latency=6)
    # await read_mem(0x00000000, 1)
    # await read_mem(0x00000001, 1)

    # await read_reg(0x400000) # ID0 == 0c86
    # await read_reg(0x400001) # ID1 == 0001
    # await read_reg(0x400800) # CR0 == 8f2f
    # await read_reg(0x400801) # CR1 == ffc1


BEE_MOVIE = Rb"""
Scripts.com
Bee Movie
By Jerry Seinfeld

NARRATOR:
(Black screen with text; The sound of buzzing bees can be heard)
According to all known laws
of aviation,
 :
there is no way a bee
should be able to fly.
 :
Its wings are too small to get
its fat little body off the ground.
 :
The bee, of course, flies anyway
 :
because bees don't care
what humans think is impossible.
BARRY BENSON:
(Barry is picking out a shirt)
Yellow, black. Yellow, black.
Yellow, black. Yellow, black.
 :
Ooh, black and yellow!
Let's shake it up a little.
JANET BENSON:
Barry! Breakfast is ready!
BARRY:
Coming!
 :
Hang on a second.
(Barry uses his antenna like a phone)
 :
Hello?
ADAM FLAYMAN:

(Through phone)
- Barry?
BARRY:
- Adam?
ADAM:
- Can you believe this is happening?
BARRY:
- I can't. I'll pick you up.
(Barry flies down the stairs)
 :
MARTIN BENSON:
Looking sharp.
JANET:
Use the stairs. Your father
paid good money for those.
BARRY:
Sorry. I'm excited.
MARTIN:
Here's the graduate.
We're very proud of you, son.
 :
A perfect report card, all B's.
JANET:
Very proud.
(Rubs Barry's hair)
BARRY=
Ma! I got a thing going here.
JANET:
- You got lint on your fuzz.
BARRY:
- Ow! That's me!

JANET:
- Wave to us! We'll be in row 118,000.
- Bye!
(Barry flies out the door)
JANET:
Barry, I told you,
stop flying in the house!
(Barry drives through the hive,and is waved at by Adam who is reading a
newspaper)
BARRY==
- Hey, Adam.
ADAM:
- Hey, Barry.
(Adam gets in Barry's car)
 :
- Is that fuzz gel?
BARRY:
- A little. Special day, graduation.
ADAM:
Never thought I'd make it.
(Barry pulls away from the house and continues driving)
BARRY:
Three days grade school,
three days high school...
ADAM:
Those were awkward.
BARRY:
Three days college. I'm glad I took
a day and hitchhiked around the hive.
ADAM==
You did come back different.
(Barry and Adam pass by Artie, who is jogging)
ARTIE:
- Hi, Barry!

BARRY:
- Artie, growing a mustache? Looks good.
ADAM:
- Hear about Frankie?
BARRY:
- Yeah.
ADAM==
- You going to the funeral?
BARRY:
- No, I'm not going to his funeral.
 :
Everybody knows,
sting someone, you die.
 :
Don't waste it on a squirrel.
Such a hothead.
ADAM:
I guess he could have
just gotten out of the way.
(The car does a barrel roll on the loop-shaped bridge and lands on the
highway)
 :
I love this incorporating
an amusement park into our regular day.
BARRY:
I guess that's why they say we don't need vacations.
(Barry parallel parks the car and together they fly over the graduating
students)
Boy, quite a bit of pomp...
under the circumstances.
(Barry and Adam sit down and put on their hats)
 :
- Well, Adam, today we are men.

ADAM:
- We are!
BARRY=
- Bee-men.
=ADAM=
- Amen!
BARRY AND ADAM:
Hallelujah!
(Barry and Adam both have a happy spasm)
ANNOUNCER:
Students, faculty, distinguished bees,
 :
please welcome Dean Buzzwell.
DEAN BUZZWELL:
Welcome, New Hive Oity
graduating class of...
 :
...9:
 :
That concludes our ceremonies.
 :
And begins your career
at Honex Industries!
ADAM:
Will we pick our job today?
(Adam and Barry get into a tour bus)
BARRY=
I heard it's just orientation.
(Tour buses rise out of the ground and the students are automatically
loaded into the buses)
TOUR GUIDE:
Heads up! Here we go.

ANNOUNCER:
Keep your hands and antennas
inside the tram at all times.
BARRY:
- Wonder what it'll be like?
ADAM:
- A little scary.
TOUR GUIDE==
Welcome to Honex,
a division of Honesco
 :
and a part of the Hexagon Group.
Barry:
This is it!
BARRY AND ADAM:
Wow.
BARRY:
Wow.
(The bus drives down a road an on either side are the Bee's massive
complicated Honey-making machines)
TOUR GUIDE:
We know that you, as a bee,
have worked your whole life
 :
to get to the point where you
can work for your whole life.
 :
Honey begins when our valiant Pollen
Jocks bring the nectar to the hive.
 :
Our top-secret formula
 :
is automatically color-corrected,

scent-adjusted and bubble-contoured
 :
into this soothing sweet syrup
 :
with its distinctive
golden glow you know as...
EVERYONE ON BUS:
Honey!
(The guide has been collecting honey into a bottle and she throws it into
the crowd on the bus and it is caught by a girl in the back)
ADAM:
- That girl was hot.
BARRY:
- She's my cousin!
ADAM==
- She is?
BARRY:
- Yes, we're all cousins.
ADAM:
- Right. You're right.
TOUR GUIDE:
- At Honex, we constantly strive
 :
to improve every aspect
of bee existence.
 :
These bees are stress-testing
a new helmet technology.
(The bus passes by a Bee wearing a helmet who is being smashed into the
ground with fly-swatters, newspapers and boots. He lifts a thumbs up but
you can hear him groan)
 :
ADAM==

- What do you think he makes?
BARRY:
- Not enough.
TOUR GUIDE:
Here we have our latest advancement,
the Krelman.
(They pass by a turning wheel with Bees standing on pegs, who are each
wearing a finger-shaped hat)
Barry:
- Wow, What does that do?
TOUR GUIDE:
- Catches that little strand of honey
 :
that hangs after you pour it.
Saves us millions.
ADAM:
(Intrigued)
Can anyone work on the Krelman?
TOUR GUIDE:
Of course. Most bee jobs are
small ones.
But bees know that every small job,
if it's done well, means a lot.
 :
But choose carefully
 :
because you'll stay in the job
you pick for the rest of your life.
(Everyone claps except for Barry)
BARRY:
The same job the rest of your life?
I didn't know that.
ADAM:

What's the difference?
TOUR GUIDE:
You'll be happy to know that bees,
as a species, haven't had one day off
 :
in 27 million years.
BARRY:
(Upset)
So you'll just work us to death?
 :
We'll sure try.
(Everyone on the bus laughs except Barry. Barry and Adam are walking back
home together)
ADAM:
Wow! That blew my mind!
BARRY:
"What's the difference?"
How can you say that?
 :
One job forever?
That's an insane choice to have to make.
ADAM:
I'm relieved. Now we only have
to make one decision in life.
BARRY:
But, Adam, how could they
never have told us that?
ADAM:
Why would you question anything?
We're bees.
 :
We're the most perfectly
functioning society on Earth.

BARRY:
You ever think maybe things
work a little too well here?
ADAM:
Like what? Give me one example.
(Barry and Adam stop walking and it is revealed to the audience that
hundreds of cars are speeding by and narrowly missing them in perfect
unison)
BARRY:
I don't know. But you know
what I'm talking about.
ANNOUNCER:
Please clear the gate.
Royal Nectar Force on approach.
BARRY:
Wait a second. Check it out.
(The Pollen jocks fly in, circle around and landing in line)
 :
- Hey, those are Pollen Jocks!
ADAM:
- Wow.
 :
I've never seen them this close.
BARRY:
They know what it's like
outside the hive.
ADAM:
Yeah, but some don't come back.
GIRL BEES:
- Hey, Jocks!
- Hi, Jocks!
(The Pollen Jocks hook up their backpacks to machines that pump the nectar
to trucks, which drive away)

LOU LO DUVA:
You guys did great!
 :
You're monsters!
You're sky freaks!
I love it!
(Punching the Pollen Jocks in joy)
I love it!
ADAM:
- I wonder where they were.
BARRY:
- I don't know.
 :
Their day's not planned.
 :
Outside the hive, flying who knows
where, doing who knows what.
 :
You can't just decide to be a Pollen
Jock. You have to be bred for that.
ADAM==
Right.
(Barry and Adam are covered in some pollen that floated off of the Pollen
Jocks)
BARRY:
Look at that. That's more pollen
than you and I will see in a lifetime.
ADAM:
It's just a status symbol.
Bees make too much of it.
BARRY:
Perhaps. Unless you're wearing it
and the ladies see you wearing it.
(Barry waves at 2 girls standing a little away from them)

ADAM==
Those ladies?
Aren't they our cousins too?
BARRY:
Distant. Distant.
POLLEN JOCK #1:
Look at these two.
POLLEN JOCK #2:
- Couple of Hive Harrys.
POLLEN JOCK #1:
- Let's have fun with them.
GIRL BEE #1:
It must be dangerous
being a Pollen Jock.
BARRY:
Yeah. Once a bear pinned me
against a mushroom!
 :
He had a paw on my throat,
and with the other, he was slapping me!
(Slaps Adam with his hand to represent his scenario)
GIRL BEE #2:
- Oh, my!
BARRY:
- I never thought I'd knock him out.
GIRL BEE #1:
(Looking at Adam)
What were you doing during this?
ADAM:
Obviously I was trying to alert the authorities.
BARRY:
I can autograph that.

(The pollen jocks walk up to Barry and Adam, they pretend that Barry and
Adam really are pollen jocks.)
POLLEN JOCK #1:
A little gusty out there today,
wasn't it, comrades?
BARRY:
Yeah. Gusty.
POLLEN JOCK #1:
We're hitting a sunflower patch
six miles from here tomorrow.
BARRY:
- Six miles, huh?
ADAM:
- Barry!
POLLEN JOCK #2:
A puddle jump for us,
but maybe you're not up for it.
BARRY:
- Maybe I am.
ADAM:
- You are not!
POLLEN JOCK #1:
We're going 0900 at J-Gate.
 :
What do you think, buzzy-boy?
Are you bee enough?
BARRY:
I might be. It all depends
on what 0900 means.
(The scene cuts to Barry looking out on the hive-city from his balcony at
night)
MARTIN:

Hey, Honex!
BARRY:
Dad, you surprised me.
MARTIN:
You decide what you're interested in?
BARRY:
- Well, there's a lot of choices.
- But you only get one.
 :
Do you ever get bored
doing the same job every day?
MARTIN:
Son, let me tell you about stirring.
 :
You grab that stick, and you just
move it around, and you stir it around.
 :
You get yourself into a rhythm.
It's a beautiful thing.
BARRY:
You know, Dad,
the more I think about it,
 :
maybe the honey field
just isn't right for me.
MARTIN:
You were thinking of what,
making balloon animals?
 :
That's a bad job
for a guy with a stinger.
 :

Janet, your son's not sure
he wants to go into honey!
JANET:
- Barry, you are so funny sometimes.
BARRY:
- I'm not trying to be funny.
MARTIN:
You're not funny! You're going
into honey. Our son, the stirrer!
JANET:
- You're gonna be a stirrer?
BARRY:
- No one's listening to me!
MARTIN:
Wait till you see the sticks I have.
BARRY:
I could say anything right now.
I'm gonna get an ant tattoo!
(Barry's parents don't listen to him and continue to ramble on)
MARTIN:
Let's open some honey and celebrate!
BARRY:
Maybe I'll pierce my thorax.
Shave my antennae.
 :
Shack up with a grasshopper. Get
a gold tooth and call everybody "dawg"!
JANET:
I'm so proud.
(The scene cuts to Barry and Adam waiting in line to get a job)
ADAM:
- We're starting work today!

BARRY:
- Today's the day.
ADAM:
Come on! All the good jobs
will be gone.
BARRY:
Yeah, right.
JOB LISTER:
Pollen counting, stunt bee, pouring,
stirrer, front desk, hair removal...
BEE IN FRONT OF LINE:
- Is it still available?
JOB LISTER:
- Hang on. Two left!
 :
One of them's yours! Congratulations!
Step to the side.
ADAM:
- What'd you get?
BEE IN FRONT OF LINE:
- Picking crud out. Stellar!
(He walks away)
ADAM:
Wow!
JOB LISTER:
Couple of newbies?
ADAM:
Yes, sir! Our first day! We are ready!
JOB LISTER:
Make your choice.
(Adam and Barry look up at the job board. There are hundreds of constantly
changing panels that contain available or unavailable jobs. It looks very
confusing)

ADAM:
- You want to go first?
BARRY:
- No, you go.
ADAM:
Oh, my. What's available?
JOB LISTER:
Restroom attendant's open,
not for the reason you think.
ADAM:
- Any chance of getting the Krelman?
JOB LISTER:
- Sure, you're on.
(Puts the Krelman finger-hat on Adam's head)
(Suddenly the sign for Krelman closes out)
 :
I'm sorry, the Krelman just closed out.
(Takes Adam's hat off)
Wax monkey's always open.
ADAM:
The Krelman opened up again.
 :
What happened?
JOB LISTER:
A bee died. Makes an opening. See?
He's dead. Another dead one.
 :
Deady. Deadified. Two more dead.
 :
Dead from the neck up.
Dead from the neck down. That's life!

ADAM:
Oh, this is so hard!
(Barry remembers what the Pollen Jock offered him and he flies off)
Heating, cooling,
stunt bee, pourer, stirrer,
 :
humming, inspector number seven,
lint coordinator, stripe supervisor,
 :
mite wrangler. Barry, what
do you think I should... Barry?
(Adam turns around and sees Barry flying away)
 :
Barry!
POLLEN JOCK:
All right, we've got the sunflower patch
in quadrant nine...
ADAM:
(Through phone)
What happened to you?
Where are you?
BARRY:
- I'm going out.
ADAM:
- Out? Out where?
BARRY:
- Out there.
ADAM:
- Oh, no!
BARRY:
I have to, before I go
to work for the rest of my life.
ADAM:

You're gonna die! You're crazy!
(Barry hangs up)
Hello?
POLLEN JOCK #2:
Another call coming in.
 :
If anyone's feeling brave,
there's a Korean deli on 83rd
 :
that gets their roses today.
BARRY:
Hey, guys.
POLLEN JOCK #1 ==
- Look at that.
POLLEN JOCK #2:
- Isn't that the kid we saw yesterday?
LOU LO DUVA:
Hold it, son, flight deck's restricted.
POLLEN JOCK #1:
It's OK, Lou. We're gonna take him up.
(Puts hand on Barry's shoulder)
LOU LO DUVA:
(To Barry) Really? Feeling lucky, are you?
BEE WITH CLIPBOARD:
(To Barry) Sign here, here. Just initial that.
 :
- Thank you.
LOU LO DUVA:
- OK.
 :
You got a rain advisory today,
 :

and as you all know,
bees cannot fly in rain.
 :
So be careful. As always,
watch your brooms,
 :
hockey sticks, dogs,
birds, bears and bats.
 :
Also, I got a couple of reports
of root beer being poured on us.
 :
Murphy's in a home because of it,
babbling like a cicada!
BARRY:
- That's awful.
LOU LO DUVA:
(Still talking through megaphone)
- And a reminder for you rookies,
 :
bee law number one,
absolutely no talking to humans!
 :
All right, launch positions!
POLLEN JOCKS:
(The Pollen Jocks run into formation)
 :
Buzz, buzz, buzz, buzz! Buzz, buzz,
buzz, buzz! Buzz, buzz, buzz, buzz!
LOU LU DUVA:
Black and yellow!
POLLEN JOCKS:

Hello!
POLLEN JOCK #1:
(To Barry)You ready for this, hot shot?
BARRY:
Yeah. Yeah, bring it on.
POLLEN JOCK's:
Wind, check.
 :
- Antennae, check.
- Nectar pack, check.
 :
- Wings, check.
- Stinger, check.
BARRY:
Scared out of my shorts, check.
LOU LO DUVA:
OK, ladies,
 :
let's move it out!
 :
Pound those petunias,
you striped stem-suckers!
 :
All of you, drain those flowers!
(The pollen jocks fly out of the hive)
BARRY:
Wow! I'm out!
 :
I can't believe I'm out!
 :
So blue.

 :
I feel so fast and free!
 :
Box kite!
(Barry flies through the kite)
 :
Wow!
 :
Flowers!
(A pollen jock puts on some high tech goggles that shows flowers similar to
heat sink goggles.)
POLLEN JOCK:
This is Blue Leader.
We have roses visual.
 :
Bring it around 30 degrees and hold.
 :
Roses!
POLLEN JOCK #1:
30 degrees, roger. Bringing it around.
 :
Stand to the side, kid.
It's got a bit of a kick.
(The pollen jock fires a high-tech gun at the flower, shooting tubes that
suck up the nectar from the flower and collects it into a pouch on the gun)
BARRY:
That is one nectar collector!
POLLEN JOCK #1==
- Ever see pollination up close?
BARRY:
- No, sir.
POLLEN JOCK #1:

(Barry and the Pollen jock fly over the field, the pollen jock sprinkles
pollen as he goes)
 :
I pick up some pollen here, sprinkle it
over here. Maybe a dash over there,
 :
a pinch on that one.
See that? It's a little bit of magic.
BARRY:
That's amazing. Why do we do that?
POLLEN JOCK #1:
That's pollen power. More pollen, more
flowers, more nectar, more honey for us.
BARRY:
Cool.
POLLEN JOCK #1:
I'm picking up a lot of bright yellow.
could be daisies. Don't we need those?
POLLEN JOCK #2:
Copy that visual.
 :
Wait. One of these flowers
seems to be on the move.
POLLEN JOCK #1:
Say again? You're reporting
a moving flower?
POLLEN JOCK #2:
Affirmative.
(The Pollen jocks land near the "flowers" which, to the audience are
obviously just tennis balls)
KEN:
(In the distance) That was on the line!

POLLEN JOCK #1:
This is the coolest. What is it?
POLLEN JOCK #2:
I don't know, but I'm loving this color.
 :
It smells good.
Not like a flower, but I like it.
POLLEN JOCK #1:
Yeah, fuzzy.
(Sticks his hand on the ball but it gets stuck)
POLLEN JOCK #3==
Chemical-y.
(The pollen jock finally gets his hand free from the tennis ball)
POLLEN JOCK #1:
Careful, guys. It's a little grabby.
(The pollen jocks turn around and see Barry lying his entire body on top of
one of the tennis balls)
POLLEN JOCK #2:
My sweet lord of bees!
POLLEN JOCK #3:
Candy-brain, get off there!
POLLEN JOCK #1:
(Pointing upwards)
Problem!
(A human hand reaches down and grabs the tennis ball that Barry is stuck
to)
BARRY:
- Guys!
POLLEN JOCK #2:
- This could be bad.
POLLEN JOCK #3:
Affirmative.
(Vanessa Bloome starts bouncing the tennis ball, not knowing Barry is stick
to it)

BARRY==
Very close.
 :
Gonna hurt.
 :
Mama's little boy.
(Barry is being hit back and forth by two humans playing tennis. He is
still stuck to the ball)
POLLEN JOCK #1:
You are way out of position, rookie!
KEN:
Coming in at you like a MISSILE!
(Barry flies past the pollen jocks, still stuck to the ball)
BARRY:
(In slow motion)
Help me!
POLLEN JOCK #2:
I don't think these are flowers.
POLLEN JOCK #3:
- Should we tell him?
POLLEN JOCK #1:
- I think he knows.
BARRY:
What is this?!
KEN:
Match point!
 :
You can start packing up, honey,
because you're about to EAT IT!
(A pollen jock coughs which confused Ken and he hits the ball the wrong way
with Barry stuck to it and it goes flying into the city)
BARRY:

Yowser!
(Barry bounces around town and gets stuck in the engine of a car. He flies
into the air conditioner and sees a bug that was frozen in there)
BARRY:
Ew, gross.
(The man driving the car turns on the air conditioner which blows Barry
into the car)
GIRL IN CAR:
There's a bee in the car!
 :
- Do something!
DAD DRIVING CAR:
- I'm driving!
BABY GIRL:
(Waving at Barry)
- Hi, bee.
(Barry smiles and waves at the baby girl)
GUY IN BACK OF CAR:
- He's back here!
 :
He's going to sting me!
GIRL IN CAR:
Nobody move. If you don't move,
he won't sting you. Freeze!
(Barry freezes as well, hovering in the middle of the car)
 :
GRANDMA IN CAR==
He blinked!
(The grandma whips out some bee-spray and sprays everywhere in the car,
climbing into the front seat, still trying to spray Barry)
GIRL IN CAR:
Spray him, Granny!
DAD DRIVING THE CAR:
What are you doing?!
(Barry escapes the car through the air conditioner and is flying high above

the ground, safe.)
BARRY:
Wow... the tension level
out here is unbelievable.
(Barry sees that storm clouds are gathering and he can see rain clouds
moving into this direction)
 :
I gotta get home.
 :
Can't fly in rain.
 :
Can't fly in rain.
(A rain drop hits Barry and one of his wings is damaged)
 :
Can't fly in rain.
(A second rain drop hits Barry again and he spirals downwards)
Mayday! Mayday! Bee going down!
(WW2 plane sound effects are played as he plummets, and he crash-lands on a
plant inside an apartment near the window)
VANESSA BLOOME:
Ken, could you close
the window please?
KEN==
Hey, check out my new resume.
I made it into a fold-out brochure.
 :
You see?
(Folds brochure resume out)
Folds out.
(Ken closes the window, trapping Barry inside)
BARRY:
Oh, no. More humans. I don't need this.
(Barry tries to fly away but smashes into the window and falls again)
 :
What was that?

(Barry keeps trying to fly out the window but he keeps being knocked back
because the window is closed)
Maybe this time. This time. This time.
This time! This time! This...
 :
Drapes!
(Barry taps the glass. He doesn't understand what it is)
That is diabolical.
KEN:
It's fantastic. It's got all my special
skills, even my top-ten favorite movies.
ANDY:
What's number one? Star Wars?
KEN:
Nah, I don't go for that...
(Ken makes finger guns and makes "pew pew pew" sounds and then stops)
 :
...kind of stuff.
BARRY:
No wonder we shouldn't talk to them.
They're out of their minds.
KEN:
When I leave a job interview, they're
flabbergasted, can't believe what I say.
BARRY:
(Looking at the light on the ceiling)
There's the sun. Maybe that's a way out.
(Starts flying towards the lightbulb)
 :
I don't remember the sun
having a big 75 on it.
(Barry hits the lightbulb and falls into the dip on the table that the
humans are sitting at)
KEN:

I predicted global warming.
 :
I could feel it getting hotter.
At first I thought it was just me.
(Andy dips a chip into the bowl and scoops up some dip with Barry on it and
is about to put it in his mouth)
 :
Wait! Stop! Bee!
(Andy drops the chip with Barry in fear and backs away. All the humans
freak out)
 :
Stand back. These are winter boots.
(Ken has winter boots on his hands and he is about to smash the bee but
Vanessa saves him last second)
VANESSA:
Wait!
 :
Don't kill him!
(Vanessa puts Barry in a glass to protect him)
KEN:
You know I'm allergic to them!
This thing could kill me!
VANESSA:
Why does his life have
less value than yours?
KEN:
Why does his life have any less value
than mine? Is that your statement?
VANESSA:
I'm just saying all life has value. You
don't know what he's capable of feeling.
(Vanessa picks up Ken's brochure and puts it under the glass so she can
carry Barry back to the window. Barry looks at Vanessa in amazement)
KEN:

My brochure!
VANESSA:
There you go, little guy.
(Vanessa opens the window and lets Barry out but Barry stays back and is
still shocked that a human saved his life)
KEN:
I'm not scared of him.
It's an allergic thing.
VANESSA:
Put that on your resume brochure.
KEN:
My whole face could puff up.
ANDY:
Make it one of your special skills.
KEN:
Knocking someone out
is also a special skill.
(Ken walks to the door)
Right. Bye, Vanessa. Thanks.
 :
- Vanessa, next week? Yogurt night?
VANESSA:
- Sure, Ken. You know, whatever.
 :
(Vanessa tries to close door)
KEN==
- You could put carob chips on there.
VANESSA:
- Bye.
(Closes door but Ken opens it again)
KEN:
- Supposed to be less calories.

VANESSA:
- Bye.
(Closes door)
(Fast forward to the next day, Barry is still inside the house. He flies
into the kitchen where Vanessa is doing dishes)
BARRY==
(Talking to himself)
I gotta say something.
 :
She saved my life.
I gotta say something.
 :
All right, here it goes.
(Turns back)
Nah.
 :
What would I say?
 :
I could really get in trouble.
 :
It's a bee law.
You're not supposed to talk to a human.
 :
I can't believe I'm doing this.
 :
I've got to.
(Barry disguises himself as a character on a food can as Vanessa walks by
again)
 :
Oh, I can't do it. Come on!
 :
No. Yes. No.
 :
Do it. I can't.

 :
How should I start it?
(Barry strikes a pose and wiggles his eyebrows)
"You like jazz?"
No, that's no good.
(Vanessa is about to walk past Barry)
Here she comes! Speak, you fool!
 :
...Hi!
(Vanessa gasps and drops the dishes in fright and notices Barry on the
counter)
 :
I'm sorry.
VANESSA:
- You're talking.
BARRY:
- Yes, I know.
VANESSA:
(Pointing at Barry)
You're talking!
BARRY:
I'm so sorry.
VANESSA:
No, it's OK. It's fine.
I know I'm dreaming.
 :
But I don't recall going to bed.
BARRY:
Well, I'm sure this
is very disconcerting.
VANESSA:
This is a bit of a surprise to me.
I mean, you're a bee!

BARRY:
I am. And I'm not supposed
to be doing this,
(Pointing to the living room where Ken tried to kill him last night)
but they were all trying to kill me.
 :
And if it wasn't for you...
 :
I had to thank you.
It's just how I was raised.
(Vanessa stabs her hand with a fork to test whether she's dreaming or not)
 :
That was a little weird.
VANESSA:
- I'm talking with a bee.
BARRY:
- Yeah.
VANESSA:
I'm talking to a bee.
And the bee is talking to me!
BARRY:
I just want to say I'm grateful.
I'll leave now.
(Barry turns to leave)
VANESSA:
- Wait! How did you learn to do that?
BARRY:
(Flying back)
- What?
VANESSA:
The talking...thing.
BARRY:

Same way you did, I guess.
"Mama, Dada, honey." You pick it up.
VANESSA:
- That's very funny.
BARRY:
- Yeah.
 :
Bees are funny. If we didn't laugh,
we'd cry with what we have to deal with.
 :
Anyway...
VANESSA:
Can I...
 :
...get you something?
BARRY:
- Like what?
VANESSA:
I don't know. I mean...
I don't know. Coffee?
BARRY:
I don't want to put you out.
VANESSA:
It's no trouble. It takes two minutes.
 :
- It's just coffee.
BARRY:
- I hate to impose.
(Vanessa starts making coffee)
VANESSA:
- Don't be ridiculous!

BARRY:
- Actually, I would love a cup.
VANESSA:
Hey, you want rum cake?
BARRY:
- I shouldn't.
VANESSA:
- Have some.
BARRY:
- No, I can't.
VANESSA:
- Come on!
BARRY:
I'm trying to lose a couple micrograms.
VANESSA:
- Where?
BARRY:
- These stripes don't help.
VANESSA:
You look great!
BARRY:
I don't know if you know
anything about fashion.
 :
Are you all right?
VANESSA:
(Pouring coffee on the floor and missing the cup completely)
No.
(Flash forward in time. Barry and Vanessa are sitting together at a table
on top of the apartment building drinking coffee)

 :
BARRY==
He's making the tie in the cab
as they're flying up Madison.
 :
He finally gets there.
 :
He runs up the steps into the church.
The wedding is on.
 :
And he says, "Watermelon?
I thought you said Guatemalan.
 :
Why would I marry a watermelon?"
(Barry laughs but Vanessa looks confused)
VANESSA:
Is that a bee joke?
BARRY:
That's the kind of stuff we do.
VANESSA:
Yeah, different.
 :
So, what are you gonna do, Barry?
(Barry stands on top of a sugar cube floating in his coffee and paddles it
around with a straw like it's a gondola)
BARRY:
About work? I don't know.
 :
I want to do my part for the hive,
but I can't do it the way they want.
VANESSA:
I know how you feel.

BARRY:
- You do?
VANESSA:
- Sure.
 :
My parents wanted me to be a lawyer or
a doctor, but I wanted to be a florist.
BARRY:
- Really?
VANESSA:
- My only interest is flowers.
BARRY:
Our new queen was just elected
with that same campaign slogan.
 :
Anyway, if you look...
(Barry points to a tree in the middle of Central Park)
 :
There's my hive right there. See it?
VANESSA:
You're in Sheep Meadow!
BARRY:
Yes! I'm right off the Turtle Pond!
VANESSA:
No way! I know that area.
I lost a toe ring there once.
BARRY:
- Why do girls put rings on their toes?
VANESSA:
- Why not?
BARRY:

- It's like putting a hat on your knee.
VANESSA:
- Maybe I'll try that.
(A custodian installing a lightbulb looks over at them but to his
perspective it looks like Vanessa is talking to a cup of coffee on the
table)
CUSTODIAN:
- You all right, ma'am?
VANESSA:
- Oh, yeah. Fine.
 :
Just having two cups of coffee!
BARRY:
Anyway, this has been great.
Thanks for the coffee.
VANESSA==
Yeah, it's no trouble.
BARRY:
Sorry I couldn't finish it. If I did,
I'd be up the rest of my life.
(Barry points towards the rum cake)
 :
Can I take a piece of this with me?
VANESSA:
Sure! Here, have a crumb.
(Vanessa hands Barry a crumb but it is still pretty big for Barry)
BARRY:
- Thanks!
VANESSA:
- Yeah.
BARRY:
All right. Well, then...
I guess I'll see you around.

 :
Or not.
VANESSA:
OK, Barry...
BARRY:
And thank you
so much again... for before.
VANESSA:
Oh, that? That was nothing.
BARRY:
Well, not nothing, but... Anyway...
(Vanessa and Barry hold hands, but Vanessa has to hold out a finger because
her hands is to big and Barry holds that)
(The custodian looks over again and it appears Vanessa is laughing at her
coffee again. The lightbulb that he was screwing in sparks and he falls off
the ladder)
(Fast forward in time and we see two Bee Scientists testing out a parachute
in a Honex wind tunnel)
BEE SCIENTIST #1:
This can't possibly work.
BEE SCIENTIST #2:
He's all set to go.
We may as well try it.
 :
OK, Dave, pull the chute.
(Dave pulls the chute and the wind slams him against the wall and he falls
on his face.The camera pans over and we see Barry and Adam walking
together)
ADAM:
- Sounds amazing.
BARRY:
- It was amazing!
 :
It was the scariest,
happiest moment of my life.

ADAM:
Humans! I can't believe
you were with humans!
 :
Giant, scary humans!
What were they like?
BARRY:
Huge and crazy. They talk crazy.
 :
They eat crazy giant things.
They drive crazy.
ADAM:
- Do they try and kill you, like on TV?
BARRY:
- Some of them. But some of them don't.
ADAM:
- How'd you get back?
BARRY:
- Poodle.
ADAM:
You did it, and I'm glad. You saw
whatever you wanted to see.
 :
You had your "experience." Now you
can pick out your job and be normal.
BARRY:
- Well...
ADAM:
- Well?
BARRY:
Well, I met someone.

ADAM:
You did? Was she Bee-ish?
 :
- A wasp?! Your parents will kill you!
BARRY:
- No, no, no, not a wasp.
ADAM:
- Spider?
BARRY:
- I'm not attracted to spiders.
 :
I know, for everyone else, it's the hottest thing,
with the eight legs and all.
 :
I can't get by that face.
ADAM:
So who is she?
BARRY:
She's... human.
ADAM:
No, no. That's a bee law.
You wouldn't break a bee law.
BARRY:
- Her name's Vanessa.
(Adam puts his head in his hands)
ADAM:
- Oh, boy.
BARRY==
She's so nice. And she's a florist!
ADAM:
Oh, no! You're dating a human florist!

BARRY:
We're not dating.
ADAM:
You're flying outside the hive, talking
to humans that attack our homes
 :
with power washers and M-80s!
That's one-eighth a stick of dynamite!
BARRY:
She saved my life!
And she understands me.
ADAM:
This is over!
BARRY:
Eat this.
(Barry gives Adam a piece of the crumb that he got from Vanessa. Adam eats
it)
ADAM:
(Adam's tone changes)
This is not over! What was that?
BARRY:
- They call it a crumb.
ADAM:
- It was so stingin' stripey!
BARRY:
And that's not what they eat.
That's what falls off what they eat!
 :
- You know what a Cinnabon is?
ADAM:
- No.
(Adam opens a door behind him and he pulls Barry in)

BARRY:
It's bread and cinnamon and frosting.
ADAM:
Be quiet!
BARRY:
They heat it up...
ADAM:
Sit down!
(Adam forces Barry to sit down)
BARRY:
(Still rambling about Cinnabons)
...really hot!
(Adam grabs Barry by the shoulders)
ADAM:
- Listen to me!
 :
We are not them! We're us.
There's us and there's them!
BARRY==
Yes, but who can deny
the heart that is yearning?
ADAM:
There's no yearning.
Stop yearning. Listen to me!
 :
You have got to start thinking bee,
my friend. Thinking bee!
BARRY:
- Thinking bee.
WORKER BEE:
- Thinking bee.
WORKER BEES AND ADAM:
Thinking bee! Thinking bee!

Thinking bee! Thinking bee!
(Flash forward in time; Barry is laying on a raft in a pool full of honey.
He is wearing sunglasses)
JANET:
There he is. He's in the pool.
MARTIN:
You know what your problem is, Barry?
(Barry pulls down his sunglasses and he looks annoyed)
BARRY:
(Sarcastic)
I gotta start thinking bee?
JANET:
How much longer will this go on?
MARTIN:
It's been three days!
Why aren't you working?
(Puts sunglasses back on)
BARRY:
I've got a lot of big life decisions
to think about.
MARTIN:
What life? You have no life!
You have no job. You're barely a bee!
JANET:
Would it kill you
to make a little honey?
(Barry rolls off the raft and sinks into the honey pool)
 :
Barry, come out.
Your father's talking to you.
 :
Martin, would you talk to him?
MARTIN:

Barry, I'm talking to you!
(Barry keeps sinking into the honey until he is suddenly in Central Park
having a picnic with Vanessa)
(Barry has a cup of honey and he clinks his glass with Vanessas. Suddenly a
mosquito lands on Vanessa and she slaps it, killing it. They both gasp but
then burst out laughing)
VANESSA:
You coming?
(The camera pans over and Vanessa is climbing into a small yellow airplane)
BARRY:
Got everything?
VANESSA:
All set!
BARRY:
Go ahead. I'll catch up.
(Vanessa lifts off and flies ahead)
VANESSA:
Don't be too long.
(Barry catches up with Vanessa and he sticks out his arms like ana irplane.
He rolls from side to side, and Vanessa copies him with the airplane)
VANESSA:
Watch this!
(Barry stays back and watches as Vanessa draws a heart in the air using
pink smoke from the plane, but on the last loop-the-loop she suddenly
crashes into a mountain and the plane explodes. The destroyed plane falls
into some rocks and explodes a second time)
BARRY:
Vanessa!
(As Barry is yelling his mouth fills with honey and he wakes up,
discovering that he was just day dreaming. He slowly sinks back into the
honey pool)
MARTIN:
- We're still here.

JANET:
- I told you not to yell at him.
 :
He doesn't respond to yelling!
MARTIN:
- Then why yell at me?
JANET:
- Because you don't listen!
MARTIN:
I'm not listening to this.
BARRY:
Sorry, I've gotta go.
MARTIN:
- Where are you going?
BARRY:
- I'm meeting a friend.
JANET:
A girl? Is this why you can't decide?
BARRY:
Bye.
(Barry flies out the door and Martin shakes his head)
 :
JANET==
I just hope she's Bee-ish.
(Fast forward in time and Barry is sitting on Vanessa's shoulder and she is
closing up her shop)
BARRY:
They have a huge parade
of flowers every year in Pasadena?
VANESSA:
To be in the Tournament of Roses,
that's every florist's dream!

 :
Up on a float, surrounded
by flowers, crowds cheering.
BARRY:
A tournament. Do the roses
compete in athletic events?
VANESSA:
No. All right, I've got one.
How come you don't fly everywhere?
BARRY:
It's exhausting. Why don't you
run everywhere? It's faster.
VANESSA:
Yeah, OK, I see, I see.
All right, your turn.
BARRY:
TiVo. You can just freeze live TV?
That's insane!
VANESSA:
You don't have that?
BARRY:
We have Hivo, but it's a disease.
It's a horrible, horrible disease.
VANESSA:
Oh, my.
(A human walks by and Barry narrowly avoids him)
PASSERBY:
Dumb bees!
VANESSA:
You must want to sting all those jerks.
BARRY:
We try not to sting.

It's usually fatal for us.
VANESSA:
So you have to watch your temper
(They walk into a store)
BARRY:
Very carefully.
You kick a wall, take a walk,
 :
write an angry letter and throw it out.
Work through it like any emotion:
 :
Anger, jealousy, lust.
(Suddenly an employee(Hector) hits Barry off of Vanessa's shoulder. Hector
thinks he's saving Vanessa)
VANESSA:
(To Barry)
Oh, my goodness! Are you OK?
(Barry is getting up off the floor)
BARRY:
Yeah.
VANESSA:
(To Hector)
- What is wrong with you?!
HECTOR:
(Confused)
- It's a bug.
VANESSA:
He's not bothering anybody.
Get out of here, you creep!
(Vanessa hits Hector across the face with the magazine he had and then hits
him in the head. Hector backs away covering his head)
Barry:
What was that? A Pic 'N' Save circular?
(Vanessa sets Barry back on her shoulder)

VANESSA:
Yeah, it was. How did you know?
BARRY:
It felt like about 10 pages.
Seventy-five is pretty much our limit.
VANESSA:
You've really got that
down to a science.
BARRY:
- Oh, we have to. I lost a cousin to Italian Vogue.
VANESSA:
- I'll bet.
(Barry looks to his right and notices there is honey for sale in the aisle)
BARRY:
What in the name
of Mighty Hercules is this?
(Barry looks at all the brands of honey, shocked)
How did this get here?
Cute Bee, Golden Blossom,
 :
Ray Liotta Private Select?
(Barry puts his hands up and slowly turns around, a look of disgust on his
face)
VANESSA:
- Is he that actor?
BARRY:
- I never heard of him.
 :
- Why is this here?
VANESSA:
- For people. We eat it.
BARRY:

You don't have
enough food of your own?!
(Hector looks back and notices that Vanessa is talking to Barry)
VANESSA:
- Well, yes.
BARRY:
- How do you get it?
VANESSA:
- Bees make it.
BARRY:
- I know who makes it!
 :
And it's hard to make it!
 :
There's heating, cooling, stirring.
You need a whole Krelman thing!
VANESSA:
- It's organic.
BARRY:
- It's our-ganic!
VANESSA:
It's just honey, Barry.
BARRY:
Just what?!
 :
Bees don't know about this!
This is stealing! A lot of stealing!
 :
You've taken our homes, schools,
hospitals! This is all we have!
 :

And it's on sale?!
I'm getting to the bottom of this.
 :
I'm getting to the bottom
of all of this!
(Flash forward in time; Barry paints his face with black strikes like a
soldier and sneaks into the storage section of the store)
(Two men, including Hector, are loading boxes into some trucks)
 :
SUPERMARKET EMPLOYEE==
Hey, Hector.
 :
- You almost done?
HECTOR:
- Almost.
(Barry takes a step to peak around the corner)
(Whispering)
He is here. I sense it.
 :
Well, I guess I'll go home now
(Hector pretends to walk away by walking in place and speaking loudly)
 :
and just leave this nice honey out,
with no one around.
BARRY:
You're busted, box boy!
HECTOR:
I knew I heard something!
So you can talk!
BARRY:
I can talk.
And now you'll start talking!
 :
Where you getting the sweet stuff?

Who's your supplier?
HECTOR:
I don't understand.
I thought we were friends.
 :
The last thing we want
to do is upset bees!
(Hector takes a thumbtack out of the board behind him and sword-fights
Barry. Barry is using his stinger like a sword)
 :
You're too late! It's ours now!
BARRY:
You, sir, have crossed
the wrong sword!
HECTOR:
You, sir, will be lunch
for my iguana, Ignacio!
(Barry hits the thumbtack out of Hectors hand and Hector surrenders)
Barry:
Where is the honey coming from?
 :
Tell me where!
HECTOR:
(Pointing to leaving truck)
Honey Farms! It comes from Honey Farms!
(Barry chases after the truck but it is getting away. He flies onto a
bicyclists' backpack and he catches up to the truck)
CAR DRIVER:
(To bicyclist)
Crazy person!
(Barry flies off and lands on the windshield of the Honey farms truck.
Barry looks around and sees dead bugs splattered everywhere)
BARRY:
What horrible thing has happened here?

 :
These faces, they never knew
what hit them. And now
 :
they're on the road to nowhere!
(Barry hears a sudden whisper)
(Barry looks up and sees Mooseblood, a mosquito playing dead)
MOOSEBLOOD:
Just keep still.
BARRY:
What? You're not dead?
MOOSEBLOOD:
Do I look dead? They will wipe anything
that moves. Where you headed?
BARRY:
To Honey Farms.
I am onto something huge here.
MOOSEBLOOD:
I'm going to Alaska. Moose blood,
crazy stuff. Blows your head off!
ANOTHER BUG PLAYING DEAD:
I'm going to Tacoma.
(Barry looks at another bug)
BARRY:
- And you?
MOOSEBLOOD:
- He really is dead.
BARRY:
All right.
(Another bug hits the windshield and the drivers notice. They activate the
windshield wipers)
MOOSEBLOOD==
Uh-oh!
(The windshield wipers are slowly sliding over the dead bugs and wiping

them off)
BARRY:
- What is that?!
MOOSEBLOOD:
- Oh, no!
 :
- A wiper! Triple blade!
BARRY:
- Triple blade?
MOOSEBLOOD:
Jump on! It's your only chance, bee!
(Mooseblood and Barry grab onto the wiper and they hold on as it wipes the
windshield)
Why does everything have
to be so doggone clean?!
 :
How much do you people need to see?!
(Bangs on windshield)
 :
Open your eyes!
Stick your head out the window!
RADIO IN TRUCK:
From NPR News in Washington,
I'm Carl Kasell.
MOOSEBLOOD:
But don't kill no more bugs!
(Mooseblood and Barry are washed off by the wipr fluid)
MOOSEBLOOD:
- Bee!
BARRY:
- Moose blood guy!!
(Barry starts screaming as he hangs onto the antenna)
(Suddenly it is revealed that a water bug is also hanging on the antenna.

There is a pause and then Barry and the water bug both start screaming)
TRUCK DRIVER:
- You hear something?
GUY IN TRUCK:
- Like what?
TRUCK DRIVER:
Like tiny screaming.
GUY IN TRUCK:
Turn off the radio.
(The antenna starts to lower until it gets to low and sinks into the truck.
The water bug flies off and Barry is forced to let go and he is blown away.
He luckily lands inside a horn on top of the truck where he finds
Mooseblood, who was blown into the same place)
MOOSEBLOOD:
Whassup, bee boy?
BARRY:
Hey, Blood.
(Fast forward in time and we see that Barry is deep in conversation with
Mooseblood. They have been sitting in this truck for a while)
BARRY:
...Just a row of honey jars,
as far as the eye could see.
MOOSEBLOOD:
Wow!
BARRY:
I assume wherever this truck goes
is where they're getting it.
 :
I mean, that honey's ours.
MOOSEBLOOD:
- Bees hang tight.
BARRY:

- We're all jammed in.
 :
It's a close community.
MOOSEBLOOD:
Not us, man. We on our own.
Every mosquito on his own.
BARRY:
- What if you get in trouble?
MOOSEBLOOD:
- You a mosquito, you in trouble.
 :
Nobody likes us. They just smack.
See a mosquito, smack, smack!
BARRY:
At least you're out in the world.
You must meet girls.
MOOSEBLOOD:
Mosquito girls try to trade up,
get with a moth, dragonfly.
 :
Mosquito girl don't want no mosquito.
(An ambulance passes by and it has a blood donation sign on it)
You got to be kidding me!
 :
Mooseblood's about to leave
the building! So long, bee!
(Mooseblood leaves and flies onto the window of the ambulance where there
are other mosquito's hanging out)
 :
- Hey, guys!
OTHER MOSQUITO:
- Mooseblood!

MOOSEBLOOD:
I knew I'd catch y'all down here.
Did you bring your crazy straw?
(The truck goes out of view and Barry notices that the truck he's on is
pulling into a camp of some sort)
TRUCK DRIVER:
We throw it in jars, slap a label on it,
and it's pretty much pure profit.
(Barry flies out)
BARRY:
What is this place?
BEEKEEPER 1#:
A bee's got a brain
the size of a pinhead.
BEEKEEPER #2:
They are pinheads!
 :
Pinhead.
 :
- Check out the new smoker.
BEEKEEPER #1:
- Oh, sweet. That's the one you want.
 :
The Thomas 3000!
BARRY:
Smoker?
BEEKEEPER #1:
Ninety puffs a minute, semi-automatic.
Twice the nicotine, all the tar.
 :
A couple breaths of this
knocks them right out.

BEEKEEPER #2:
They make the honey,
and we make the money.
BARRY:
"They make the honey,
and we make the money"?
(The Beekeeper sprays hundreds of cheap miniature apartments with the
smoker. The bees are fainting or passing out)
Oh, my!
 :
What's going on? Are you OK?
(Barry flies into one of the apartment and helps a Bee couple get off the
ground. They are coughing and its hard for them to stand)
BEE IN APARTMENT:
Yeah. It doesn't last too long.
BARRY:
Do you know you're
in a fake hive with fake walls?
BEE IN APPARTMENT:
Our queen was moved here.
We had no choice.
(The apartment room is completely empty except for a photo on the wall of
the "queen" who is obviously a man in women's clothes)
BARRY:
This is your queen?
That's a man in women's clothes!
 :
That's a drag queen!
 :
What is this?
(Barry flies out and he discovers that there are hundreds of these
structures, each housing thousands of Bees)
Oh, no!
 :
There's hundreds of them!
(Barry takes out his camera and takes pictures of these Bee work camps. The
beekeepers look very evil in these depictions)

Bee honey.
 :
Our honey is being brazenly stolen
on a massive scale!
 :
This is worse than anything bears
have done! I intend to do something.
(Flash forward in time and Barry is showing these pictures to his parents)
JANET:
Oh, Barry, stop.
MARTIN:
Who told you humans are taking
our honey? That's a rumor.
BARRY:
Do these look like rumors?
(Holds up the pictures)
UNCLE CARL:
That's a conspiracy theory.
These are obviously doctored photos.
JANET:
How did you get mixed up in this?
ADAM:
He's been talking to humans.
JANET:
- What?
MARTIN:
- Talking to humans?!
ADAM:
He has a human girlfriend.
And they make out!
JANET:
Make out? Barry!

BARRY:
We do not.
ADAM:
- You wish you could.
MARTIN:
- Whose side are you on?
BARRY:
The bees!
UNCLE CARL:
(He has been sitting in the back of the room this entire time)
I dated a cricket once in San Antonio.
Those crazy legs kept me up all night.
JANET:
Barry, this is what you want
to do with your life?
BARRY:
I want to do it for all our lives.
Nobody works harder than bees!
 :
Dad, I remember you
coming home so overworked
 :
your hands were still stirring.
You couldn't stop.
JANET:
I remember that.
BARRY:
What right do they have to our honey?
 :
We live on two cups a year. They put it
in lip balm for no reason whatsoever!

ADAM:
Even if it's true, what can one bee do?
BARRY:
Sting them where it really hurts.
MARTIN:
In the face! The eye!
 :
- That would hurt.
BARRY:
- No.
MARTIN:
Up the nose? That's a killer.
BARRY:
There's only one place you can sting
the humans, one place where it matters.
(Flash forward a bit in time and we are watching the Bee News)
BEE NEWS NARRATOR:
Hive at Five, the hive's only
full-hour action news source.
BEE PROTESTOR:
No more bee beards!
BEE NEWS NARRATOR:
With Bob Bumble at the anchor desk.
 :
Weather with Storm Stinger.
 :
Sports with Buzz Larvi.
 :
And Jeanette Chung.
BOB BUMBLE:
- Good evening. I'm Bob Bumble.
JEANETTE CHUNG:

- And I'm Jeanette Chung.
BOB BUMBLE:
A tri-county bee, Barry Benson,
 :
intends to sue the human race
for stealing our honey,
 :
packaging it and profiting
from it illegally!
JEANETTE CHUNG:
Tomorrow night on Bee Larry King,
 :
we'll have three former queens here in
our studio, discussing their new book,
 :
Classy Ladies,
out this week on Hexagon.
(The scene changes to an interview on the news with Bee version of Larry
King and Barry)
BEE LARRY KING:
Tonight we're talking to Barry Benson.
 :
Did you ever think, "I'm a kid
from the hive. I can't do this"?
BARRY:
Bees have never been afraid
to change the world.
 :
What about Bee Columbus?
Bee Gandhi? Bejesus?
BEE LARRY KING:
Where I'm from, we'd never sue humans.

 :
We were thinking
of stickball or candy stores.
BARRY:
How old are you?
BEE LARRY KING:
The bee community
is supporting you in this case,
 :
which will be the trial
of the bee century.
BARRY:
You know, they have a Larry King
in the human world too.
BEE LARRY KING:
It's a common name. Next week...
BARRY:
He looks like you and has a show
and suspenders and colored dots...
BEE LARRY KING:
Next week...
BARRY:
Glasses, quotes on the bottom from the
guest even though you just heard 'em.
BEE LARRY KING:
Bear Week next week!
They're scary, hairy and here, live.
(Bee Larry King gets annoyed and flies away offscreen)
BARRY:
Always leans forward, pointy shoulders,
squinty eyes, very Jewish.
(Flash forward in time. We see Vanessa enter and Ken enters behind her.
They are arguing)

KEN:
In tennis, you attack
at the point of weakness!
VANESSA:
It was my grandmother, Ken. She's 81.
KEN==
Honey, her backhand's a joke!
I'm not gonna take advantage of that?
BARRY:
(To Ken)
Quiet, please.
Actual work going on here.
KEN:
(Pointing at Barry)
- Is that that same bee?
VANESSA:
- Yes, it is!
 :
I'm helping him sue the human race.
BARRY:
- Hello.
KEN:
- Hello, bee.
VANESSA:
This is Ken.
BARRY:
(Recalling the "Winter Boots" incident earlier)
Yeah, I remember you. Timberland, size
ten and a half. Vibram sole, I believe.
KEN:
(To Vanessa)
Why does he talk again?
VANESSA:

Listen, you better go
'cause we're really busy working.
KEN:
But it's our yogurt night!
VANESSA:
(Holding door open for Ken)
Bye-bye.
KEN:
(Yelling)
Why is yogurt night so difficult?!
(Ken leaves and Vanessa walks over to Barry. His workplace is a mess)
VANESSA:
You poor thing.
You two have been at this for hours!
BARRY:
Yes, and Adam here
has been a huge help.
ADAM:
- Frosting...
- How many sugars?
 ==BARRY==
Just one. I try not
to use the competition.
 :
So why are you helping me?
VANESSA:
Bees have good qualities.
 :
And it takes my mind off the shop.
 :
Instead of flowers, people
are giving balloon bouquets now.
BARRY:

Those are great, if you're three.
VANESSA:
And artificial flowers.
BARRY:
- Oh, those just get me psychotic!
VANESSA:
- Yeah, me too.
 :
BARRY:
Bent stingers, pointless pollination.
ADAM:
Bees must hate those fake things!
 :
Nothing worse
than a daffodil that's had work done.
 :
Maybe this could make up
for it a little bit.
VANESSA:
- This lawsuit's a pretty big deal.
BARRY:
- I guess.
ADAM:
You sure you want to go through with it?
BARRY:
Am I sure? When I'm done with
the humans, they won't be able
 :
to say, "Honey, I'm home,"
without paying a royalty!
(Flash forward in time and we are watching the human news. The camera shows

a crowd outside a courthouse)
NEWS REPORTER:
It's an incredible scene
here in downtown Manhattan,
 :
where the world anxiously waits,
because for the first time in history,
 :
we will hear for ourselves
if a honeybee can actually speak.
(We are no longer watching through a news camera)
ADAM:
What have we gotten into here, Barry?
BARRY:
It's pretty big, isn't it?
ADAM==
(Looking at the hundreds of people around the courthouse)
I can't believe how many humans
don't work during the day.
BARRY:
You think billion-dollar multinational
food companies have good lawyers?
SECURITY GUARD:
Everybody needs to stay
behind the barricade.
(A limousine drives up and a fat man,Layton Montgomery, a honey industry
owner gets out and walks past Barry)
ADAM:
- What's the matter?
BARRY:
- I don't know, I just got a chill.
(Fast forward in time and everyone is in the court)
MONTGOMERY:
Well, if it isn't the bee team.

(To Honey Industry lawyers)
You boys work on this?
MAN:
All rise! The Honorable
Judge Bumbleton presiding.
JUDGE BUMBLETON:
All right. Case number 4475,
 :
Superior Court of New York,
Barry Bee Benson v. the Honey Industry
 :
is now in session.
 :
Mr. Montgomery, you're representing
the five food companies collectively?
MONTGOMERY:
A privilege.
JUDGE BUMBLETON:
Mr. Benson... you're representing
all the bees of the world?
(Everyone looks closely, they are waiting to see if a Bee can really talk)
(Barry makes several buzzing sounds to sound like a Bee)
BARRY:
I'm kidding. Yes, Your Honor,
we're ready to proceed.
JUDGE BUMBLBETON:
Mr. Montgomery,
your opening statement, please.
MONTGOMERY:
Ladies and gentlemen of the jury,
 :
my grandmother was a simple woman.
 :

Born on a farm, she believed
it was man's divine right
 :
to benefit from the bounty
of nature God put before us.
 :
If we lived in the topsy-turvy world
Mr. Benson imagines,
 :
just think of what would it mean.
 :
I would have to negotiate
with the silkworm
 :
for the elastic in my britches!
 :
Talking bee!
(Montgomery walks over and looks closely at Barry)
 :
How do we know this isn't some sort of
 :
holographic motion-picture-capture
Hollywood wizardry?
 :
They could be using laser beams!
 :
Robotics! Ventriloquism!
Cloning! For all we know,
 :
he could be on steroids!
JUDGE BUMBLETON:
Mr. Benson?

BARRY:
Ladies and gentlemen,
there's no trickery here.
 :
I'm just an ordinary bee.
Honey's pretty important to me.
 :
It's important to all bees.
We invented it!
 :
We make it. And we protect it
with our lives.
 :
Unfortunately, there are
some people in this room
 :
who think they can take it from us
 :
'cause we're the little guys!
I'm hoping that, after this is all over,
 :
you'll see how, by taking our honey,
you not only take everything we have
 :
but everything we are!
JANET==
(To Martin)
I wish he'd dress like that
all the time. So nice!
JUDGE BUMBLETON:
Call your first witness.
BARRY:
So, Mr. Klauss Vanderhayden

of Honey Farms, big company you have.
KLAUSS VANDERHAYDEN:
I suppose so.
BARRY:
I see you also own
Honeyburton and Honron!
KLAUSS:
Yes, they provide beekeepers
for our farms.
BARRY:
Beekeeper. I find that
to be a very disturbing term.
 :
I don't imagine you employ
any bee-free-ers, do you?
KLAUSS:
(Quietly)
- No.
BARRY:
- I couldn't hear you.
KLAUSS:
- No.
BARRY:
- No.
 :
Because you don't free bees.
You keep bees. Not only that,
 :
it seems you thought a bear would be
an appropriate image for a jar of honey.
KLAUSS:
They're very lovable creatures.

 :
Yogi Bear, Fozzie Bear, Build-A-Bear.
BARRY:
You mean like this?
(The bear from Over The Hedge barges in through the back door and it is
roaring and standing on its hind legs. It is thrashing its claws and people
are screaming. It is being held back by a guard who has the bear on a
chain)
 :
(Pointing to the roaring bear)
Bears kill bees!
 :
How'd you like his head crashing
through your living room?!
 :
Biting into your couch!
Spitting out your throw pillows!
JUDGE BUMBLETON:
OK, that's enough. Take him away.
(The bear stops roaring and thrashing and walks out)
BARRY:
So, Mr. Sting, thank you for being here.
Your name intrigues me.
 :
- Where have I heard it before?
MR. STING:
- I was with a band called The Police.
BARRY:
But you've never been
a police officer, have you?
STING:
No, I haven't.
BARRY:

No, you haven't. And so here
we have yet another example
 :
of bee culture casually
stolen by a human
 :
for nothing more than
a prance-about stage name.
STING:
Oh, please.
BARRY:
Have you ever been stung, Mr. Sting?
 :
Because I'm feeling
a little stung, Sting.
 :
Or should I say... Mr. Gordon M. Sumner!
MONTGOMERY:
That's not his real name?! You idiots!
BARRY:
Mr. Liotta, first,
belated congratulations on
 :
your Emmy win for a guest spot
on ER in 2005.
RAY LIOTTA:
Thank you. Thank you.
BARRY:
I see from your resume
that you're devilishly handsome
 :
with a churning inner turmoil

that's ready to blow.
RAY LIOTTA:
I enjoy what I do. Is that a crime?
BARRY:
Not yet it isn't. But is this
what it's come to for you?
 :
Exploiting tiny, helpless bees
so you don't
 :
have to rehearse
your part and learn your lines, sir?
RAY LIOTTA:
Watch it, Benson!
I could blow right now!
BARRY:
This isn't a goodfella.
This is a badfella!
(Ray Liotta looses it and tries to grab Barry)
RAY LIOTTA:
Why doesn't someone just step on
this creep, and we can all go home?!
JUDGE BUMBLETON:
- Order in this court!
RAY LIOTTA:
- You're all thinking it!
(Judge Bumbleton starts banging her gavel)
JUDGE BUMBLETON:
Order! Order, I say!
RAY LIOTTA:
- Say it!
MAN:

- Mr. Liotta, please sit down!
(We see a montage of magazines which feature the court case)
(Flash forward in time and Barry is back home with Vanessa)
BARRY:
I think it was awfully nice
of that bear to pitch in like that.
VANESSA:
I think the jury's on our side.
BARRY:
Are we doing everything right,you know, legally?
VANESSA:
I'm a florist.
BARRY:
Right. Well, here's to a great team.
VANESSA:
To a great team!
(Ken walks in from work. He sees Barry and he looks upset when he sees
Barry clinking his glass with Vanessa)
KEN:
Well, hello.
VANESSA:
- Oh, Ken!
BARRY:
- Hello!
VANESSA:
I didn't think you were coming.
 :
No, I was just late.
I tried to call, but...
(Ken holds up his phone and flips it open. The phone has no charge)
...the battery...
VANESSA:

I didn't want all this to go to waste,
so I called Barry. Luckily, he was free.
KEN:
Oh, that was lucky.
(Ken sits down at the table across from Barry and Vanessa leaves the room)
VANESSA:
There's a little left.
I could heat it up.
KEN:
(Not taking his eyes off Barry)
Yeah, heat it up, sure, whatever.
BARRY:
So I hear you're quite a tennis player.
 :
I'm not much for the game myself.
The ball's a little grabby.
KEN:
That's where I usually sit.
Right...
(Points to where Barry is sitting)
there.
VANESSA:
(Calling from other room)
Ken, Barry was looking at your resume,
 :
and he agreed with me that eating with
chopsticks isn't really a special skill.
KEN:
(To Barry)
You think I don't see what you're doing?
BARRY:
I know how hard it is to find
the right job. We have that in common.

KEN:
Do we?
BARRY:
Bees have 100 percent employment,
but we do jobs like taking the crud out.
KEN:
(Menacingly)
That's just what
I was thinking about doing.
(Ken reaches for a fork on the table but knocks if on the floor. He goes to
pick it up)
VANESSA:
Ken, I let Barry borrow your razor
for his fuzz. I hope that was all right.
(Ken quickly rises back up after hearing this but hits his head on the
table and yells)
BARRY:
I'm going to drain the old stinger.
KEN:
Yeah, you do that.
(Barry flies past Ken to get to the bathroom and Ken freaks out, splashing
some of the wine he was using to cool his head in his eyes. He yells in
anger)
(Barry looks at the magazines featuring his victories in court)
BARRY:
Look at that.
(Barry flies into the bathroom)
(He puts his hand on his head but this makes hurts him and makes him even
madder. He yells again)
(Barry is washing his hands in the sink but then Ken walks in)
KEN:
You know, you know I've just about had it
(Closes bathroom door behind him)
with your little mind games.
(Ken is menacingly rolling up a magazine)
BARRY:

(Backing away)
- What's that?
KEN:
- Italian Vogue.
BARRY:
Mamma mia, that's a lot of pages.
KEN:
It's a lot of ads.
BARRY:
Remember what Van said, why is
your life more valuable than mine?
KEN:
That's funny, I just can't seem to recall that!
(Ken smashes everything off the sink with the magazine and Barry narrowly
escapes)
(Ken follows Barry around and tries to hit him with the magazine but he
keeps missing)
(Ken gets a spray bottle)
 :
I think something stinks in here!
BARRY:
(Enjoying the spray)
I love the smell of flowers.
(Ken holds a lighter in front of the spray bottle)
KEN:
How do you like the smell of flames?!
BARRY:
Not as much.
(Ken fires his make-shift flamethrower but misses Barry, burning the
bathroom. He torches the whole room but looses his footing and falls into
the bathtub. After getting hit in the head by falling objects 3 times he
picks up the shower head, revealing a Water bug hiding under it)
WATER BUG:
Water bug! Not taking sides!

(Barry gets up out of a pile of bathroom supplies and he is wearing a
chapstick hat)
BARRY:
Ken, I'm wearing a Chapstick hat!
This is pathetic!
(Ken switches the shower head to lethal)
KEN:
I've got issues!
(Ken sprays Barry with the shower head and he crash lands into the toilet)
(Ken menacingly looks down into the toilet at Barry)
Well, well, well, a royal flush!
BARRY:
- You're bluffing.
KEN:
- Am I?
(flushes toilet)
(Barry grabs a chapstick from the toilet seat and uses it to surf in the
flushing toilet)
BARRY:
Surf's up, dude!
(Barry flies out of the toilet on the chapstick and sprays Ken's face with
the toilet water)
 :
EW,Poo water!
BARRY:
That bowl is gnarly.
KEN:
(Aiming a toilet cleaner at Barry)
Except for those dirty yellow rings!
(Barry cowers and covers his head and Vanessa runs in and takes the toilet
cleaner from Ken just before he hits Barry)
VANESSA:
Kenneth! What are you doing?!
KEN==
(Leaning towards Barry)

You know, I don't even like honey!
I don't eat it!
VANESSA:
We need to talk!
(Vanessa pulls Ken out of the bathroom)
 :
He's just a little bee!
 :
And he happens to be
the nicest bee I've met in a long time!
KEN:
Long time? What are you talking about?!
Are there other bugs in your life?
VANESSA:
No, but there are other things bugging
me in life. And you're one of them!
KEN:
Fine! Talking bees, no yogurt night...
 :
My nerves are fried from riding
on this emotional roller coaster!
VANESSA:
Goodbye, Ken.
(Ken huffs and walks out and slams the door. But suddenly he walks back in
and stares at Barry)
 :
And for your information,
I prefer sugar-free, artificial
sweeteners MADE BY MAN!
(Ken leaves again and Vanessa leans in towards Barry)
VANESSA:
I'm sorry about all that.
(Ken walks back in again)

KEN:
I know it's got
an aftertaste! I LIKE IT!
(Ken leaves for the last time)
VANESSA:
I always felt there was some kind
of barrier between Ken and me.
 :
I couldn't overcome it.
Oh, well.
 :
Are you OK for the trial?
BARRY:
I believe Mr. Montgomery
is about out of ideas.
(Flash forward in time and Barry, Adam, and Vanessa are back in court)
MONTGOMERY--
We would like to call
Mr. Barry Benson Bee to the stand.
ADAM:
Good idea! You can really see why he's
considered one of the best lawyers...
(Barry stares at Adam)
...Yeah.
LAWYER:
Layton, you've
gotta weave some magic
with this jury,
or it's gonna be all over.
MONTGOMERY:
Don't worry. The only thing I have
to do to turn this jury around
 :
is to remind them
of what they don't like about bees.
(To lawyer)

- You got the tweezers?
LAWYER:
- Are you allergic?
MONTGOMERY:
Only to losing, son. Only to losing.
 :
Mr. Benson Bee, I'll ask you
what I think we'd all like to know.
 :
What exactly is your relationship
(Points to Vanessa)
 :
to that woman?
BARRY:
We're friends.
MONTGOMERY:
- Good friends?
BARRY:
- Yes.
MONTGOMERY:
How good? Do you live together?
ADAM:
Wait a minute...
 :
MONTGOMERY:
Are you her little...
 :
...bedbug?
(Adam's stinger starts vibrating. He is agitated)
I've seen a bee documentary or two.
From what I understand,

 :
doesn't your queen give birth
to all the bee children?
BARRY:
- Yeah, but...
MONTGOMERY:
(Pointing at Janet and Martin)
- So those aren't your real parents!
JANET:
- Oh, Barry...
BARRY:
- Yes, they are!
ADAM:
Hold me back!
(Vanessa tries to hold Adam back. He wants to sting Montgomery)
MONTGOMERY:
You're an illegitimate bee,
aren't you, Benson?
ADAM:
He's denouncing bees!
MONTGOMERY:
Don't y'all date your cousins?
(Montgomery leans over on the jury stand and stares at Adam)
VANESSA:
- Objection!
(Vanessa raises her hand to object but Adam gets free. He flies straight at
Montgomery)
=ADAM:
- I'm going to pincushion this guy!
BARRY:
Adam, don't! It's what he wants!
(Adam stings Montgomery in the butt and he starts thrashing around)

MONTGOMERY:
Oh, I'm hit!!
 :
Oh, lordy, I am hit!
JUDGE BUMBLETON:
(Banging gavel)
Order! Order!
MONTGOMERY:
(Overreacting)
The venom! The venom
is coursing through my veins!
 :
I have been felled
by a winged beast of destruction!
 :
You see? You can't treat them
like equals! They're striped savages!
 :
Stinging's the only thing
they know! It's their way!
BARRY:
- Adam, stay with me.
ADAM:
- I can't feel my legs.
MONTGOMERY:
(Overreacting and throwing his body around the room)
What angel of mercy
will come forward to suck the poison
 :
from my heaving buttocks?
JUDGE BUMLBETON:
I will have order in this court. Order!

 :
Order, please!
(Flash forward in time and we see a human news reporter)
NEWS REPORTER:
The case of the honeybees
versus the human race
 :
took a pointed turn against the bees
 :
yesterday when one of their legal
team stung Layton T. Montgomery.
(Adam is laying in a hospital bed and Barry flies in to see him)
BARRY:
- Hey, buddy.
ADAM:
- Hey.
BARRY:
- Is there much pain?
ADAM:
- Yeah.
 :
I...
 :
I blew the whole case, didn't I?
BARRY:
It doesn't matter. What matters is
you're alive. You could have died.
ADAM:
I'd be better off dead. Look at me.
(A small plastic sword is replaced as Adam's stinger)
They got it from the cafeteria
downstairs, in a tuna sandwich.

 :
Look, there's
a little celery still on it.
(Flicks off the celery and sighs)
BARRY:
What was it like to sting someone?
ADAM:
I can't explain it. It was all...
 :
All adrenaline and then...
and then ecstasy!
BARRY:
...All right.
ADAM:
You think it was all a trap?
BARRY:
Of course. I'm sorry.
I flew us right into this.
 :
What were we thinking? Look at us. We're
just a couple of bugs in this world.
ADAM:
What will the humans do to us
if they win?
BARRY:
I don't know.
ADAM:
I hear they put the roaches in motels.
That doesn't sound so bad.
BARRY:
Adam, they check in,
but they don't check out!

ADAM:
Oh, my.
(Coughs)
Could you get a nurse
to close that window?
BARRY:
- Why?
ADAM:
- The smoke.
(We can see that two humans are smoking cigarettes outside)
 :
Bees don't smoke.
BARRY:
Right. Bees don't smoke.
 :
Bees don't smoke!
But some bees are smoking.
 :
That's it! That's our case!
ADAM:
It is? It's not over?
BARRY:
Get dressed. I've gotta go somewhere.
 :
Get back to the court and stall.
Stall any way you can.
(Flash forward in time and Adam is making a paper boat in the courtroom)
ADAM:
And assuming you've done step 29 correctly, you're ready for the tub!
(We see that the jury have each made their own paper boats after being
taught how by Adam. They all look confused)
JUDGE BUMBLETON:

Mr. Flayman.
ADAM:
Yes? Yes, Your Honor!
JUDGE BUMBLETON:
Where is the rest of your team?
ADAM:
(Continues stalling)
Well, Your Honor, it's interesting.
 :
Bees are trained to fly haphazardly,
 :
and as a result,
we don't make very good time.
 :
I actually heard a funny story about...
MONTGOMERY:
Your Honor,
haven't these ridiculous bugs
 :
taken up enough
of this court's valuable time?
 :
How much longer will we allow
these absurd shenanigans to go on?
 :
They have presented no compelling
evidence to support their charges
 :
against my clients,
who run legitimate businesses.
 :
I move for a complete dismissal

of this entire case!
JUDGE BUMBLETON:
Mr. Flayman, I'm afraid I'm going
 :
to have to consider
Mr. Montgomery's motion.
ADAM:
But you can't! We have a terrific case.
MONTGOMERY:
Where is your proof?
Where is the evidence?
 :
Show me the smoking gun!
BARRY:
(Barry flies in through the door)
Hold it, Your Honor!
You want a smoking gun?
 :
Here is your smoking gun.
(Vanessa walks in holding a bee smoker. She sets it down on the Judge's
podium)
JUDGE BUMBLETON:
What is that?
BARRY:
It's a bee smoker!
MONTGOMERY:
(Picks up smoker)
What, this?
This harmless little contraption?
 :
This couldn't hurt a fly,
let alone a bee.
(Montgomery accidentally fires it at the bees in the crowd and they faint

and cough)
(Dozens of reporters start taking pictures of the suffering bees)
BARRY:
Look at what has happened
 :
to bees who have never been asked,
"Smoking or non?"
 :
Is this what nature intended for us?
 :
To be forcibly addicted
to smoke machines
 :
and man-made wooden slat work camps?
 :
Living out our lives as honey slaves
to the white man?
(Barry points to the honey industry owners. One of them is an African
American so he awkwardly separates himself from the others)
LAWYER:
- What are we gonna do?
- He's playing the species card.
BARRY:
Ladies and gentlemen, please,
free these bees!
ADAM AND VANESSA:
Free the bees! Free the bees!
BEES IN CROWD:
Free the bees!
HUMAN JURY:
Free the bees! Free the bees!
JUDGE BUMBLETON:
The court finds in favor of the bees!

BARRY:
Vanessa, we won!
VANESSA:
I knew you could do it! High-five!
(Vanessa hits Barry hard because her hand is too big)
 :
Sorry.
BARRY:
(Overjoyed)
I'm OK! You know what this means?
 :
All the honey
will finally belong to the bees.
 :
Now we won't have
to work so hard all the time.
MONTGOMERY:
This is an unholy perversion
of the balance of nature, Benson.
 :
You'll regret this.
(Montgomery leaves and Barry goes outside the courtroom. Several reporters
start asking Barry questions)
REPORTER 1#:
Barry, how much honey is out there?
BARRY:
All right. One at a time.
REPORTER 2#:
Barry, who are you wearing?
BARRY:
My sweater is Ralph Lauren,
and I have no pants.

(Barry flies outside with the paparazzi and Adam and Vanessa stay back)
ADAM:
(To Vanessa)
- What if Montgomery's right?
Vanessa:
- What do you mean?
ADAM:
We've been living the bee way
a long time, 27 million years.
(Flash forward in time and Barry is talking to a man)
BUSINESS MAN:
Congratulations on your victory.
What will you demand as a settlement?
BARRY:
First, we'll demand a complete shutdown
of all bee work camps.
(As Barry is talking we see a montage of men putting "closed" tape over the
work camps and freeing the bees in the crappy apartments)
Then we want back the honey
that was ours to begin with,
 :
every last drop.
(Men in suits are pushing all the honey of the aisle and into carts)
We demand an end to the glorification
of the bear as anything more
(We see a statue of a bear-shaped honey container being pulled down by
bees)
than a filthy, smelly,
bad-breath stink machine.
 :
We're all aware
of what they do in the woods.
(We see Winnie the Pooh sharing his honey with Piglet in the cross-hairs of
a high-tech sniper rifle)
BARRY:
(Looking through binoculars)

Wait for my signal.
 :
Take him out.
(Winnie gets hit by a tranquilizer dart and dramatically falls off the log
he was standing on, his tongue hanging out. Piglet looks at Pooh in fear
and the Sniper takes the honey.)
SNIPER:
He'll have nausea
for a few hours, then he'll be fine.
(Flash forward in time)
BARRY:
And we will no longer tolerate
bee-negative nicknames...
(Mr. Sting is sitting at home until he is taken out of his house by the men
in suits)
STING:
But it's just a prance-about stage name!
BARRY:
...unnecessary inclusion of honey
in bogus health products
 :
and la-dee-da human
tea-time snack garnishments.
(An old lady is mixing honey into her tea but suddenly men in suits smash
her face down on the table and take the honey)
OLD LADY:
Can't breathe.
(A honey truck pulls up to Barry's hive)
WORKER:
Bring it in, boys!
 :
Hold it right there! Good.
 :
Tap it.

(Tons of honey is being pumped into the hive's storage)
BEE WORKER 1#:
(Honey overflows from the cup)
Mr. Buzzwell, we just passed three cups,
and there's gallons more coming!
 :
- I think we need to shut down!
=BEE WORKER #2=
- Shut down? We've never shut down.
 :
Shut down honey production!
DEAN BUZZWELL:
Stop making honey!
(The bees all leave their stations. Two bees run into a room and they put
the keys into a machine)
Turn your key, sir!
(Two worker bees dramatically turn their keys, which opens the button which
they press, shutting down the honey-making machines. This is the first time
this has ever happened)
BEE:
...What do we do now?
(Flash forward in time and a Bee is about to jump into a pool full of
honey)
Cannonball!
(The bee gets stuck in the honey and we get a short montage of Bees leaving
work)
(We see the Pollen Jocks flying but one of them gets a call on his antenna)
LOU LU DUVA:
(Through "phone")
We're shutting honey production!
 :
Mission abort.
POLLEN JOCK #1:
Aborting pollination and nectar detail.
Returning to base.
(The Pollen Jocks fly back to the hive)

(We get a time lapse of Central Park slowly wilting away as the bees all
relax)
BARRY:
Adam, you wouldn't believe
how much honey was out there.
ADAM:
Oh, yeah?
BARRY:
What's going on? Where is everybody?
(The entire street is deserted)
 :
- Are they out celebrating?
ADAM:
- They're home.
 :
They don't know what to do.
Laying out, sleeping in.
 :
I heard your Uncle Carl was on his way
to San Antonio with a cricket.
BARRY:
At least we got our honey back.
ADAM:
Sometimes I think, so what if humans
liked our honey? Who wouldn't?
 :
It's the greatest thing in the world!
I was excited to be part of making it.
 :
This was my new desk. This was my
new job. I wanted to do it really well.
 :

And now...
 :
Now I can't.
(Flash forward in time and Barry is talking to Vanessa)
BARRY:
I don't understand
why they're not happy.
 :
I thought their lives would be better!
 :
They're doing nothing. It's amazing.
Honey really changes people.
VANESSA:
You don't have any idea
what's going on, do you?
BARRY:
- What did you want to show me?
(Vanessa takes Barry to the rooftop where they first had coffee and points
to her store)
VANESSA:
- This.
(Points at her flowers. They are all grey and wilting)
BARRY:
What happened here?
VANESSA:
That is not the half of it.
(Small flash forward in time and Vanessa and Barry are on the roof of her
store and she points to Central Park)
(We see that Central Park is no longer green and colorful, rather it is
grey, brown, and dead-like. It is very depressing to look at)
BARRY:
Oh, no. Oh, my.
 :

They're all wilting.
VANESSA:
Doesn't look very good, does it?
BARRY:
No.
VANESSA:
And whose fault do you think that is?
BARRY:
You know, I'm gonna guess bees.
VANESSA==
(Staring at Barry)
Bees?
BARRY:
Specifically, me.
 :
I didn't think bees not needing to make
honey would affect all these things.
VANESSA:
It's not just flowers.
Fruits, vegetables, they all need bees.
BARRY:
That's our whole SAT test right there.
VANESSA:
Take away produce, that affects
the entire animal kingdom.
 :
And then, of course...
BARRY:
The human species?
 :
So if there's no more pollination,

 :
it could all just go south here,
couldn't it?
VANESSA:
I know this is also partly my fault.
BARRY:
How about a suicide pact?
VANESSA:
How do we do it?
BARRY:
- I'll sting you, you step on me.
VANESSA:
- That just kills you twice.
BARRY:
Right, right.
VANESSA:
Listen, Barry...
sorry, but I gotta get going.
(Vanessa leaves)
BARRY:
(To himself)
I had to open my mouth and talk.
 :
Vanessa?
 :
Vanessa? Why are you leaving?
Where are you going?
(Vanessa is getting into a taxi)
VANESSA:
To the final Tournament of Roses parade
in Pasadena.
 :

They've moved it to this weekend
because all the flowers are dying.
 :
It's the last chance
I'll ever have to see it.
BARRY:
Vanessa, I just wanna say I'm sorry.
I never meant it to turn out like this.
VANESSA:
I know. Me neither.
(The taxi starts to drive away)
BARRY:
Tournament of Roses.
Roses can't do sports.
 :
Wait a minute. Roses. Roses?
 :
Roses!
 :
Vanessa!
(Barry flies after the Taxi)
VANESSA:
Roses?!
 :
Barry?
(Barry is flying outside the window of the taxi)
BARRY:
- Roses are flowers!
VANESSA:
- Yes, they are.
BARRY:
Flowers, bees, pollen!

VANESSA:
I know.
That's why this is the last parade.
BARRY:
Maybe not.
Could you ask him to slow down?
VANESSA:
Could you slow down?
(The taxi driver screeches to a stop and Barry keeps flying forward)
 :
Barry!
(Barry flies back to the window)
BARRY:
OK, I made a huge mistake.
This is a total disaster, all my fault.
VANESSA:
Yes, it kind of is.
BARRY:
I've ruined the planet.
I wanted to help you
 :
with the flower shop.
I've made it worse.
VANESSA:
Actually, it's completely closed down.
BARRY:
I thought maybe you were remodeling.
 :
But I have another idea, and it's
greater than my previous ideas combined.
VANESSA:
I don't want to hear it!

BARRY:
All right, they have the roses,
the roses have the pollen.
 :
I know every bee, plant
and flower bud in this park.
 :
All we gotta do is get what they've got
back here with what we've got.
 :
- Bees.
VANESSA:
- Park.
BARRY:
- Pollen!
VANESSA:
- Flowers.
BARRY:
- Re-pollination!
VANESSA:
- Across the nation!
 :
Tournament of Roses,
Pasadena, California.
 :
They've got nothing
but flowers, floats and cotton candy.
 :
Security will be tight.
BARRY:
I have an idea.

(Flash forward in time. Vanessa is about to board a plane which has all the
Roses on board.
VANESSA:
Vanessa Bloome, FTD.
(Holds out badge)
 :
Official floral business. It's real.
SECURITY GUARD:
Sorry, ma'am. Nice brooch.
=VANESSA==
Thank you. It was a gift.
(Barry is revealed to be hiding inside the brooch)
(Flash back in time and Barry and Vanessa are discussing their plan)
BARRY:
Once inside,
we just pick the right float.
VANESSA:
How about The Princess and the Pea?
 :
I could be the princess,
and you could be the pea!
BARRY:
Yes, I got it.
 :
- Where should I sit?
GUARD:
- What are you?
BARRY:
- I believe I'm the pea.
GUARD:
- The pea?
VANESSA:

It goes under the mattresses.
GUARD:
- Not in this fairy tale, sweetheart.
- I'm getting the marshal.
VANESSA:
You do that!
This whole parade is a fiasco!
 :
Let's see what this baby'll do.
(Vanessa drives the float through traffic)
GUARD:
Hey, what are you doing?!
BARRY==
Then all we do
is blend in with traffic...
 :
...without arousing suspicion.
 :
Once at the airport,
there's no stopping us.
(Flash forward in time and Barry and Vanessa are about to get on a plane)
SECURITY GUARD:
Stop! Security.
 :
- You and your insect pack your float?
VANESSA:
- Yes.
SECURITY GUARD:
Has it been
in your possession the entire time?
VANESSA:
- Yes.

SECURITY GUARD:
Would you remove your shoes?
(To Barry)
- Remove your stinger.
BARRY:
- It's part of me.
SECURITY GUARD:
I know. Just having some fun.
Enjoy your flight.
(Barry plotting with Vanessa)
BARRY:
Then if we're lucky, we'll have
just enough pollen to do the job.
(Flash forward in time and Barry and Vanessa are flying on the plane)
Can you believe how lucky we are? We
have just enough pollen to do the job!
VANESSA:
I think this is gonna work.
BARRY:
It's got to work.
CAPTAIN SCOTT:
(On intercom)
Attention, passengers,
this is Captain Scott.
 :
We have a bit of bad weather
in New York.
 :
It looks like we'll experience
a couple hours delay.
VANESSA:
Barry, these are cut flowers
with no water. They'll never make it.
BARRY:

I gotta get up there
and talk to them.
VANESSA==
Be careful.
(Barry flies right outside the cockpit door)
BARRY:
Can I get help
with the Sky Mall magazine?
I'd like to order the talking
inflatable nose and ear hair trimmer.
(The flight attendant opens the door and walks out and Barry flies into the
cockpit unseen)
BARRY:
Captain, I'm in a real situation.
CAPTAIN SCOTT:
- What'd you say, Hal?
CO-PILOT HAL:
- Nothing.
(Scott notices Barry and freaks out)
CAPTAIN SCOTT:
Bee!
BARRY:
No,no,no, Don't freak out! My entire species...
(Captain Scott gets out of his seat and tries to suck Barry into a handheld
vacuum)
HAL:
(To Scott)
What are you doing?
(Barry lands on Hals hair but Scott sees him. He tries to suck up Barry but
instead he sucks up Hals toupee)
CAPTAIN SCOTT:
Uh-oh.
BARRY:
- Wait a minute! I'm an attorney!

HAL:
(Hal doesn't know Barry is on his head)
- Who's an attorney?
CAPTAIN SCOTT:
Don't move.
(Scott hits Hal in the face with the vacuum in an attempt to hit Barry. Hal
is knocked out and he falls on the life raft button which launches an
infalatable boat into Scott, who gets knocked out and falls to the floor.
They are both uncounscious.)
BARRY:
(To himself)
Oh, Barry.
BARRY:
(On intercom, with a Southern accent)
Good afternoon, passengers.
This is your captain.
 :
Would a Miss Vanessa Bloome in 24B
please report to the cockpit?
(Vanessa looks confused)
(Normal accent)
...And please hurry!
(Vanessa opens the door and sees the life raft and the uncounscious pilots)
VANESSA:
What happened here?
BARRY:
I tried to talk to them, but
then there was a DustBuster,
a toupee, a life raft exploded.
 :
Now one's bald, one's in a boat,
and they're both unconscious!
VANESSA:
...Is that another bee joke?
BARRY:

- No!
 :
No one's flying the plane!
BUD DITCHWATER:
(Through radio on plane)
This is JFK control tower, Flight 356.
What's your status?
VANESSA:
This is Vanessa Bloome.
I'm a florist from New York.
BUD:
Where's the pilot?
VANESSA:
He's unconscious,
and so is the copilot.
BUD:
Not good. Does anyone onboard
have flight experience?
BARRY:
As a matter of fact, there is.
BUD:
- Who's that?
BARRY:
- Barry Benson.
BUD:
From the honey trial?! Oh, great.
BARRY:
Vanessa, this is nothing more
than a big metal bee.
 :
It's got giant wings, huge engines.

VANESSA:
I can't fly a plane.
BARRY:
- Why not? Isn't John Travolta a pilot?
VANESSA:
- Yes.
BARRY:
How hard could it be?
(Vanessa sits down and flies for a little bit but we see lightning clouds
outside the window)
VANESSA:
Wait, Barry!
We're headed into some lightning.
(An ominous lightning storm looms in front of the plane)
(We are now watching the Bee News)
BOB BUMBLE:
This is Bob Bumble. We have some
late-breaking news from JFK Airport,
 :
where a suspenseful scene
is developing.
 :
Barry Benson,
fresh from his legal victory...
ADAM:
That's Barry!
BOB BUMBLE:
...is attempting to land a plane,
loaded with people, flowers
 :
and an incapacitated flight crew.
JANET, MARTIN, UNCLE CAR AND ADAM:
Flowers?!
(The scene switches to the human news)

REPORTER:
(Talking with Bob Bumble)
We have a storm in the area
and two individuals at the controls
 :
with absolutely no flight experience.
BOB BUMBLE:
Just a minute.
There's a bee on that plane.
BUD:
I'm quite familiar with Mr. Benson
and his no-account compadres.
 :
They've done enough damage.
REPORTER:
But isn't he your only hope?
BUD:
Technically, a bee
shouldn't be able to fly at all.
 :
Their wings are too small...
BARRY:
(Through radio)
Haven't we heard this a million times?
 :
"The surface area of the wings
and body mass make no sense."...
BOB BUMBLE:
- Get this on the air!
BEE:
- Got it.

BEE NEWS CREW:
- Stand by.
BEE NEWS CREW:
- We're going live!
BARRY:
(Through radio on TV)
...The way we work may be a mystery to you.
 :
Making honey takes a lot of bees
doing a lot of small jobs.
 :
But let me tell you about a small job.
 :
If you do it well,
it makes a big difference.
 :
More than we realized.
To us, to everyone.
 :
That's why I want to get bees
back to working together.
 :
That's the bee way!
We're not made of Jell-O.
 :
We get behind a fellow.
 :
- Black and yellow!
BEES:
- Hello!
(The scene switches and Barry is teaching Vanessa how to fly)
BARRY:

Left, right, down, hover.
VANESSA:
- Hover?
BARRY:
- Forget hover.
VANESSA:
This isn't so hard.
(Pretending to honk the horn)
Beep-beep! Beep-beep!
(A Lightning bolt hits the plane and autopilot turns off)
Barry, what happened?!
BARRY:
Wait, I think we were
on autopilot the whole time.
VANESSA:
- That may have been helping me.
BARRY:
- And now we're not!
VANESSA:
So it turns out I cannot fly a plane.
(The plane plummets but we see Lou Lu Duva and the Pollen Jocks, along with
multiple other bees flying towards the plane)
Lou Lu DUva:
All of you, let's get
behind this fellow! Move it out!
 :
Move out!
(The scene switches back to Vanessa and Barry in the plane)
BARRY:
Our only chance is if I do what I'd do,
you copy me with the wings of the plane!
(Barry sticks out his arms like an airplane and flys in front of Vanessa's
face)

VANESSA:
Don't have to yell.
BARRY:
I'm not yelling!
We're in a lot of trouble.
VANESSA:
It's very hard to concentrate
with that panicky tone in your voice!
BARRY:
It's not a tone. I'm panicking!
VANESSA:
I can't do this!
(Barry slaps Vanessa)
BARRY:
Vanessa, pull yourself together.
You have to snap out of it!
VANESSA:
(Slaps Barry)
You snap out of it.
BARRY:
(Slaps Vanessa)
 :
You snap out of it.
VANESSA:
- You snap out of it!
BARRY:
- You snap out of it!
(We see that all the Pollen Jocks are flying under the plane)
VANESSA:
- You snap out of it!
BARRY:
- You snap out of it!

VANESSA:
- You snap out of it!
BARRY:
- You snap out of it!
VANESSA:
- Hold it!
BARRY:
- Why? Come on, it's my turn.
VANESSA:
How is the plane flying?
(The plane is now safely flying)
VANESSA:
I don't know.
(Barry's antennae rings like a phone. Barry picks up)
BARRY:
Hello?
LOU LU DUVA:
(Through "phone")
Benson, got any flowers
for a happy occasion in there?
(All of the Pollen Jocks are carrying the plane)
BARRY:
The Pollen Jocks!
 :
They do get behind a fellow.
LOU LU DUVA:
- Black and yellow.
POLLEN JOCKS:
- Hello.
LOU LU DUVA:
All right, let's drop this tin can

on the blacktop.
BARRY:
Where? I can't see anything. Can you?
VANESSA:
No, nothing. It's all cloudy.
 :
Come on. You got to think bee, Barry.
BARRY:
- Thinking bee.
- Thinking bee.
(On the runway there are millions of bees laying on their backs)
BEES:
Thinking bee!
Thinking bee! Thinking bee!
BARRY:
Wait a minute.
I think I'm feeling something.
VANESSA:
- What?
BARRY:
- I don't know. It's strong, pulling me.
 :
Like a 27-million-year-old instinct.
 :
Bring the nose down.
BEES:
Thinking bee!
Thinking bee! Thinking bee!
CONTROL TOWER OPERATOR:
- What in the world is on the tarmac?
BUD:
- Get some lights on that!

(It is revealed that all the bees are organized into a giant pulsating
flower formation)
BEES:
Thinking bee!
Thinking bee! Thinking bee!
BARRY:
- Vanessa, aim for the flower.
VANESSA:
- OK.
BARRY:
Out the engines. We're going in
on bee power. Ready, boys?
LOU LU DUVA:
Affirmative!
BARRY:
Good. Good. Easy, now. That's it.
 :
Land on that flower!
 :
Ready? Full reverse!
 :
Spin it around!
(The plane's nose is pointed at a flower painted on a nearby plane)
- Not that flower! The other one!
VANESSA:
- Which one?
BARRY:
- That flower.
(The plane is now pointed at a fat guy in a flowered shirt. He freaks out
and tries to take a picture of the plane)
VANESSA:
- I'm aiming at the flower!

BARRY:
That's a fat guy in a flowered shirt.
I mean the giant pulsating flower
made of millions of bees!
(The plane hovers over the bee-flower)
 :
Pull forward. Nose down. Tail up.
 :
Rotate around it.
VANESSA:
- This is insane, Barry!
BARRY:
- This's the only way I know how to fly.
BUD:
Am I koo-koo-kachoo, or is this plane
flying in an insect-like pattern?
(The plane is unrealistically hovering and spinning over the bee-flower)
BARRY:
Get your nose in there. Don't be afraid.
Smell it. Full reverse!
 :
Just drop it. Be a part of it.
 :
Aim for the center!
 :
Now drop it in! Drop it in, woman!
 :
Come on, already.
(The bees scatter and the plane safely lands)
VANESSA:
Barry, we did it!
You taught me how to fly!

BARRY:
- Yes!
(Vanessa is about to high-five Barry)
No high-five!
VANESSA:
- Right.
ADAM:
Barry, it worked!
Did you see the giant flower?
BARRY:
What giant flower? Where? Of course
I saw the flower! That was genius!
ADAM:
- Thank you.
BARRY:
- But we're not done yet.
 :
Listen, everyone!
 :
This runway is covered
with the last pollen
 :
from the last flowers
available anywhere on Earth.
 :
That means this is our last chance.
 :
We're the only ones who make honey,
pollinate flowers and dress like this.
 :
If we're gonna survive as a species,
this is our moment! What do you say?

 :
Are we going to be bees, or just
Museum of Natural History keychains?
BEES:
We're bees!
BEE WHO LIKES KEYCHAINS:
Keychain!
BARRY:
Then follow me! Except Keychain.
POLLEN JOCK #1:
Hold on, Barry. Here.
 :
You've earned this.
BARRY:
Yeah!
 :
I'm a Pollen Jock! And it's a perfect
fit. All I gotta do are the sleeves.
(The Pollen Jocks throw Barry a nectar-collecting gun. Barry catches it)
Oh, yeah.
JANET:
That's our Barry.
(Barry and the Pollen Jocks get pollen from the flowers on the plane)
(Flash forward in time and the Pollen Jocks are flying over NYC)
 :
(Barry pollinates the flowers in Vanessa's shop and then heads to Central
Park)
BOY IN PARK:
Mom! The bees are back!
ADAM:
(Putting on his Krelman hat)
If anybody needs

to make a call, now's the time.
 :
I got a feeling we'll be
working late tonight!
(The bee honey factories are back up and running)
(Meanwhile at Vanessa's shop)
VANESSA:
(To customer)
Here's your change. Have a great
afternoon! Can I help who's next?
 :
Would you like some honey with that?
It is bee-approved. Don't forget these.
(There is a room in the shop where Barry does legal work for other animals.
He is currently talking with a Cow)
COW:
Milk, cream, cheese, it's all me.
And I don't see a nickel!
 :
Sometimes I just feel
like a piece of meat!
BARRY:
I had no idea.
VANESSA:
Barry, I'm sorry.
Have you got a moment?
BARRY:
Would you excuse me?
My mosquito associate will help you.
MOOSEBLOOD:
Sorry I'm late.
COW:
He's a lawyer too?

MOOSEBLOOD:
Ma'am, I was already a blood-sucking parasite.
All I needed was a briefcase.
VANESSA:
Have a great afternoon!
 :
Barry, I just got this huge tulip order,
and I can't get them anywhere.
BARRY:
No problem, Vannie.
Just leave it to me.
VANESSA:
You're a lifesaver, Barry.
Can I help who's next?
BARRY:
All right, scramble, jocks!
It's time to fly.
VANESSA:
Thank you, Barry!
(Ken walks by on the sidewalk and sees the "bee-approved honey" in
Vanessa's shop)
KEN:
That bee is living my life!!
ANDY:
Let it go, Kenny.
KEN:
- When will this nightmare end?!
ANDY:
- Let it all go.
BARRY:
- Beautiful day to fly.
POLLEN JOCK:

- Sure is.
BARRY:
Between you and me,
I was dying to get out of that office.
(Barry recreates the scene near the beginning of the movie where he flies
through the box kite. The movie fades to black and the credits being)
[--after credits; No scene can be seen but the characters can be heard
talking over the credits--]
You have got
to start thinking bee, my friend!
 :
- Thinking bee!
- Me?
BARRY:
(Talking over singer)
Hold it. Let's just stop
for a second. Hold it.
 :
I'm sorry. I'm sorry, everyone.
Can we stop here?
SINGER:
Oh, BarryBARRY:
I'm not making a major life decision
during a production number!
SINGER:
All right. Take ten, everybody.
Wrap it up, guys.
BARRY:
I had virtually no rehearsal for that.
"""

if __name__ == "__main__":
    asyncio.run(main())
