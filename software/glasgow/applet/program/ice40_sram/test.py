import base64
import zlib

from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_hardware_test
from . import ProgramICE40SRAMApplet, ICE40SRAMError


class ProgramICE40SRAMAppletTestCase(GlasgowAppletV2TestCase, applet=ProgramICE40SRAMApplet):
    @synthesis_test
    def test_build_with_done(self):
        self.assertBuilds(args=["--done", "A4"])

    @synthesis_test
    def test_build_without_done(self):
        self.assertBuilds(args=["--done", "-"])

    # For the next two tests, the FPGA should configure successfully.

    @applet_v2_hardware_test(args=["-V", "3.3", "--done", "A4"],
            mocks=[f"ice40_iface.{attr}" for attr in ["_spi_iface", "_reset_iface", "_done_iface"]])
    async def test_hardware_with_done(self, applet: ProgramICE40SRAMApplet):
        await applet.ice40_iface.load(ICE40UP5K_BLINKY_BITSTREAM)

    @applet_v2_hardware_test(args=["-V", "3.3", "--done", "-"],
            mocks=[f"ice40_iface.{attr}" for attr in ["_spi_iface", "_reset_iface", "_done_iface"]])
    async def test_hardware_without_done(self, applet: ProgramICE40SRAMApplet):
        await applet.ice40_iface.load(ICE40UP5K_BLINKY_BITSTREAM)

    # For the next test, the configuration should fail. (Leave everything disconnected.)

    @applet_v2_hardware_test(args=["-V", "3.3", "--done", "A4"],
            mocks=[f"ice40_iface.{attr}" for attr in ["_spi_iface", "_reset_iface", "_done_iface"]])
    async def test_hardware_failure(self, applet: ProgramICE40SRAMApplet):
        try:
            await applet.ice40_iface.load(ICE40UP5K_BLINKY_BITSTREAM)
            self.fail("expected an error")
        except ICE40SRAMError:
            pass


ICE40UP5K_BLINKY_BITSTREAM = zlib.decompress(base64.b85decode(R"""
c%1Fs;fo`89mny{Op?9acJDTe_1LPMK`f?f&(JM+lodu0AC>M(MQRIm>4VZfJNAK8kTSgk5iImj%2hnh
JE$mqbm~8ldQTUu&-95bKJ$UF5Bj+6@B2$~x5*}x-|sr(CC&Q-J2T0AGyBTqH@}(5?64n8AHV+IZ(sj`
lE$yqekuLyWobXz-B6N<5JE`hS?ji|SnQoD77A8i1=a!<tiTGa1uR&B6<7;cumUTv7O-Ho^jN#7;IQ@n
qgH>E-JRufd{$ste{`p?;`pq<GO%EWS(pvX0(R-K3$=lP1v|*XY+x3!U<K9!7OcPutOYDsffZN_Sg-;s
uokdj1y*1!V8IHkz*@k96<C3_fCVeC0&4*aR$v9z0v4>m3akYzSb-H-3)scMF4P~Wg9SUt!fap`uuG3!
s0|D(*g+O%1G9hyE3g)@U<FoSEnvY4tiW2pf)!YSwSWaHumWoV3sztS)&dr+mK~c&`?|f6EcriV%+5r<
V0Yxv-t@xy%moc9y6&eryhwRG6F-@gWg|J2tLG<D8ywk!$J3thvI%9MJ`b*CO}hMha`s5l(tdgDl8*c^
$^0m^Ira+Yx@E1{`u~!B*!FHOg)Mbfn;l76Z6@=>yBF?{#^<+^-h@{Lyd(edC)vpIXF6si_rtWm5#3z_
!K-4e8(3I#KlNH~%}r%TGwpXm+gw-A>6P!e*0a~>omkQ13C6}H80&HvTp5I28I0?n&!mUdTA%rf7;NLe
KeSPDb9~LV$15Y&?C`U{7*HF5&4VlNrx|1cPeovVmiy64ag|Th23C6{|DLoRP#v*>DS6`^>z=dO#lhIL
|A95fpPZav?8SaBdN}fAHl;YK8FU}ZtS`_0Ftajd15@&<f7^|BXB9?aT|es@SJLZa^VamrC~Rk2z4Wl%
xM>f%+MHS#zh;$Y2lgO;|L57%eRc%)IVG>y_`;PZ-7wj|*30rKr4iVMp3S7QshS5fYs0a5{?K1+e0csh
Gq>C*>=$;<+QdU!e(6QE5o`91Tfg|w#%Hh3Tn8~bh1LGJ)AZPzMYR#w!MV-Ki*FiswWu@#d%AVWx7p6=
13M)9->rh$m^GXC+w3z}wrwBz?`(Q$%m%hz+p&JO?V3S*^kgp|FAc{w-A8of+SHy~v$ecYSQ~Y0@PbFR
FKk&aaP@Eb^drTXV}mpAx#6w7ANAYpvwxai8nc0|emRrv6u$1;tiE0F(g^GaXP$6pL+Pm-zRfCq`h%&Z
QP|&I_7mUg_p@Is2m7x-zUIg0eAktvPftGvpN8%ANA2U!t$xlwn{^KSF~ZjPOOG8l6k|tP=8ymUvW?Ok
hE3kNAMB*8>RfK)^#i{zua&cAlWW!+<a>Unu&d|S%E9K>Z1`~daci?JmDCJ2*FS9An}6}T|G?6cu#bF{
%T8<7x7<0ibfu&<`}R*|*!uN@M2~9!9`?i$O#pUnaCCM0syphkcKOW%>u2+#*UZMYhp+!f-rd%Jw0Hi>
b}d)3JMqh|VC*oBU;0Bt*JfQmThmdy;DkSX&2DbCF4>l~cg~tYYg5@|Z2#_x(Ay^JjizDU^y3G!@2*G#
Z=2|5xnbYe_iY24c`HaTR;#sjo9=vLD=7`@rdw`z>!zP^YqnJE-~F`Pz?8Mle6?LBHa+k5VD+Y+%H6U*
JvJFmU)b_x-J?>l{~S!$2WxhxRdADy!c%+8hMoSwcVVK=!RoHFN?yKU8(1SRDvbM*!|%a5?m))9_uHL<
FVbSLwZZYM^|MK?o#~Y^-y2w5Z`JwYmhTHo+1(Dli#n8kV#l-6Q*V}X)OEMzoi=%LwWu<x8NBvgH(1GA
)@@Hct%>aog3981gP^ke#@bh&6=3tDDzJrR^R{Lm2v(Yluj#`Bc8;)FKutV0&1ctq*4J!Ez=9Q6fwh1I
E3g7<0Si`O1=a!<tiTGa1uR&B6<7;cumUTv7O;zi-A{Hm(j~tEmk>h!4{3FKRV=o)R>e}mf)!W`Sg-;s
uokdj1y*1!V8IHkz*@k96<7_h_iq2RwELsn50B3ZEVEf2TUc>#R$!T%1s3cOTYl&bz>0o$A$tR`^s~Jx
77G@vzzVDdELedRSPNLN0xPf<uwVsNU@c(53ar3dz=9Q6fwh1IE3g7<0Si`O1=a!<tiTGa1uR&B6<7<{
#ljM@kSYHU)B`K>h_c}<u*;5JsGR~>u;P9&unUSUKlBD*1y*1!V8IHkz*@k96<C3_fCVeC0&4*aR$v9z
0v4>m3akYzSXK9TUHiJdQTr_aL&iL?u35z|zZg;53#^N42=(Em&zZlz6}8;Jr4BE{KG?J$G$1NjB}+Y3
$x<syyPC~$4id3<xD{NPMC={v5o@-RU0Dn^Ci9F<vau)T8G9n-U~i5-oNw${zzQr_AFyBr7OW501;W;=
!RD1<o7G@5n!$Wv^U%V1z)sKDsa=)W((kTFs=2!YEZ8Bo^vri}Fcz>{K<q+oU|_-aRDS3U1Qx6hSg-;M
)(0$Dfd%UW7OcR6^#Kc3V8Qx;1uL*%eZYbhSg<}|!CLl}Z|Ji0l764ms`(X!5JCtcWPWp5IY)wo5JCtc
OPP(te=E4du^=I2nd8rj=?MuTOP!6BYsG{RLI@$t8m<)+LI@#*ENeDuTq`Do5Uv#yLdaKs^=`7FPXJ0P
S^x
""".replace("\n", "")))
