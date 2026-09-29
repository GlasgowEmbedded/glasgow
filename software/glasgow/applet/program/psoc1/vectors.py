# Ref: CY8C21x12, CY8C21x23, CY8C21x34, CY8C23x33, CY8C24x23A, CY8C27x43, CY8CTMG110, CY8CTST110 PSoC® 1 ISSP Programming Specifications Rev. K
# Document Number: 001-13617 (Also known using its old name as "AN2026a")
# Accession: G00090

# Ref: CY8C21x45, CY8C22x45, CY8C24x94, CY8C28xxx, CY8C29x66, CY8CTST120, CY8CTMA120, CY8CTMG120, CY7C64215 PSoC® 1 ISSP Programming Specifications Rev. L
# Document Number: 001-15239 (Also known using its old name as "AN2026b")
# Accession: G00091

# Ref: CY8C20045, CY8C20055, CY8C20xx6, CY8C20xx6A, CY8C20xx6AS, CY8C20xx6AN, CY8C20xx6L, CY8C20xx6H, CY7C643xx, CY7C604xx, CY8CTST2xx, CY8CTMG2xx, CY8C20xx7, CY8C20xx7S, and CY8C20xx7AN ISSP Programming Specifications Rev. I
# Document Number: 001-57631 (Also known using its old name as "AN2026c")
# Accession: G00091

import re
from collections import namedtuple

INITIALIZE_1 = ( # Matches ISSP Specs: RevK, RevL
    "11001010000000000000000000000000000000000000" +
    "00000000000000000000000000000000000000000000" +
    "00000000000000000000000000000000000000000000" +
    "11011110111000000001111101111011000000000111" +
    "10011111000001110101111001111100100000011111" +
    "11011110101000000001111101111010000000011111" +
    "10011111011100000001111101111100100110000111" +
    "11011111010010000001111101111000000001001111" +
    "11011111000000000001111101111111100010010111")

INITIALIZE_2 = ( # Matches ISSP Specs: RevK, RevL
    "11011110111000000001111101111011000000000111" +
    "10011111000001110101111001111100100000011111" +
    "11011110101000000001111101111010000000011111" +
    "10011111011100000001111101111100100110000111" +
    "11011111010010000001111001111101000000001111" +
    "11011110000000001101111101111100000000000111" +
    "1101111111100010010111")

INITIALIZE_3_3V = ( # Matches ISSP Specs: RevK, RevL
    "11011110111000000001111101111010000000011111" +
    "11011110101000000001111101111011000001000111" +
    "11011111000010100011111101111100111111000111" +
    "11011111010001100001111101111111100010010111" +
    "00000000000000000000001101111011100000000111" +
    "11011110100000000111111101111010100000000111" +
    "11011110110000010001111101111100001100000111" +
    "11011111001111010101111101111101000110000111" +
    "11011110111000100001111101111111100010010111" +
    "00000000000000000000001101111011100000000111" +
    "11011110100000000111111101111010100000000111" +
    "11011110110000010001111101111100001010001111" +
    "11011111001111110011111101111101000110000111" +
    "11011111111000100101110000000000000000000000" +
    "11011110111000000001111101111010000000011111" +
    "11011110101000000001111101111011000001000111" +
    "11011111000011000001111101111100111101000111" +
    "11011111010001100001111101111011100010000111" +
    "11011111111000100101110000000000000000000000")

INITIALIZE_3_5V = ( # Matches ISSP Specs: RevK, RevL
    "11011110111000000001111101111010000000011111" +
    "11011110101000000001111101111011000001000111" +
    "11011111000010100011111101111100111111100111" +
    "11011111010001100001111101111111100010010111" +
    "00000000000000000000001101111011100000000111" +
    "11011110100000000111111101111010100000000111" +
    "11011110110000010001111101111100001100000111" +
    "11011111001111010101111101111101000110000111" +
    "11011110111000100001111101111111100010010111" +
    "00000000000000000000001101111011100000000111" +
    "11011110100000000111111101111010100000000111" +
    "11011110110000010001111101111100001010001111" +
    "11011111001111111011111101111101000110000111" +
    "11011111111000100101110000000000000000000000" +
    "11011110111000000001111101111010000000011111" +
    "11011110101000000001111101111011000001000111" +
    "11011111000011000001111101111100111101000111" +
    "11011111010001100001111101111011100010000111" +
    "11011111111000100101110000000000000000000000")

ID_SETUP = ( # Matches ISSP Specs: RevK, RevL
    "11011110111000100001111101110000000000010111" +
    "11011110111000000001111101111011000000000111" +
    "10011111000001110101111001111100100000011111" +
    "11011110101000000001111101111010000000011111" +
    "10011111011100000001111101111100100110000111" +
    "11011111010010000001111001111101000000000111" +
    "11011110000000001101111101111100000000000111" +
    "1101111111100010010111")

ID_SETUP_1 = ( # Matches ISSP Specs: RevI (in this code used by init_type=1)
    "110010100000000000000000000000000000000000000000000000000000000000" +
    "000000000000000000000000000000000000000000000000000000000000000000" +
    "110111101110001000011111011111110000001001111101110001000000100111" +
    "110111000000000001111111011110111000000001111001111100000111010111" +
    "100111110010000001111110011111011000100001111101111011100010000111" +
    "110111111100000000011111011100010000000001111101110000000000011111" +
    "110111101110000000011111011110100000000111111101111010100000000111" +
    "110111101100000000011111011110000000010011111101111100000000000111" +
    "110111110010100000011111011111010001100001111101111111100010010110")

SYNC_ENABLE = ( # Matches ISSP Specs: RevI (in this code used by init_type=1)
    "110111101110001000011111011111110000001001111101110001000000100111" +
    "11011100000000000111111101111011100000000111")

SYNC_DISABLE = ( # Matches ISSP Specs: RevI (in this code used by init_type=1)
    "110111101110001000011111011100010000000001111101111111000000000111" +
    "11011100000000000111111101111011100000000111")

ID_SETUP_2 = ( # Matches ISSP Specs: RevI (in this code used by init_type=1)
    "110111101110001000011111011111110000001001111101110001000000100111" +
    "110111000000000001111110011111000001110101111001111100100000011111" +
    "100111110100000000011111011111110000000001111101110001000000000111" +
    "110111000000000001111111011110111000000001111101111010000000011111" +
    "110111101010000000011111011110110000000001111101111000000000110111" +
    "110111110000000000011111011111001010000001111101111101000110000111" +
    "1101111111100010010110")


BULK_ERASE = ( # Matches ISSP Specs: RevK, RevL
    "10011111100000101011111001111111001010110111" +
    "11011110111000000001111101111011000000000111" +
    "10011111000001110101111001111100100000011111" +
    "11011110101000000001111101111010000000011111" +
    "10011111011100000001111101111100100110000111" +
    "11011111010010000001111101111000000000101111" +
    "11011111000000000001111101111111100010010111")

ERASE = ( # Matches ISSP Specs: RevI (in this code used by erase_type=1)
    "110111101110001000011111011111110000001001111101110001000000100111" +
    "110111000000000001111110011111000001110101111001111100100001011111" +
    "110111111100000000011111011100010000000001111101110000000000011111" +
    "110111101110000000011111011110000000001011111101111010000000011111" +
    "110111101010000000011111011110110000010001111101111100000000000111" +
    "110111110010011000011111011111010010000001111101111111100010010110")

class PartNumberMatcher:
    def __init__(self, *descriptors):
        assert len(descriptors) >= 1
        self.descriptors = tuple(descriptors)
        sub_regexes = []
        for descriptor in descriptors:
            rstr = descriptor.replace("x", ".")
            if "-" not in rstr:
                rstr += "(?:-.*)?"
            else:
                rstr += ".*"
            rstr = "(?:" + rstr + ")"
            sub_regexes.append(rstr)
        self.regex = re.compile("|".join(sub_regexes))

    def __str__(self):
        return " / ".join(self.descriptors)

    def __repr__(self):
        args = ", ".join([repr(descriptor) for descriptor in self.descriptors])
        return f"PartNumberMatcher({args})"

    def __eq__(self, other):
        return self.descriptors == other.descriptors

    def __ne__(self, other):
        return self.descriptors != other.descriptors

    def __hash__(self):
        return hash(("PartNumberMatcher", self.descriptors))

    def fullmatch(self, part_to_match):
        return self.regex.fullmatch(part_to_match)

class SiliconId:
    def __init__(self, *id_bytes):
        assert len(id_bytes) >= 1
        self.id_bytes = id_bytes

    def __str__(self):
        return "(" + (", ".join([f"0x{idbyte:02x}" for idbyte in self.id_bytes])) + ")"

    def __repr__(self):
        return "SiliconId(" + (", ".join([f"0x{idbyte:02x}" for idbyte in self.id_bytes])) + ")"

    def __eq__(self, other):
        if isinstance(other, SiliconId):
            return self.id_bytes == other.id_bytes
        return self.id_bytes == other

    def __ne__(self, other):
        if isinstance(other, SiliconId):
            return self.id_bytes != other.id_bytes
        return self.id_bytes != other

    def __hash__(self):
        return hash(("SiliconId", self.id_bytes))

silicon_ids = {
    (SiliconId(0b0000_0000, 0b0000_1001), PartNumberMatcher("CY8C27143")),            # RevK
    (SiliconId(0b0000_0000, 0b0000_1010), PartNumberMatcher("CY8C27243")),            # RevK
    (SiliconId(0b0000_0000, 0b0000_1011), PartNumberMatcher("CY8C27443")),            # RevK
    (SiliconId(0b0000_0000, 0b0000_1100), PartNumberMatcher("CY8C27543")),            # RevK
    (SiliconId(0b0000_0000, 0b0000_1101), PartNumberMatcher("CY8C27643")),            # RevK
    (SiliconId(0b0000_0000, 0b0011_0010), PartNumberMatcher("CY8C24123A")),           # RevK
    (SiliconId(0b0000_0000, 0b0011_0011), PartNumberMatcher("CY8C24223A")),           # RevK
    (SiliconId(0b0000_0000, 0b0011_0100), PartNumberMatcher("CY8C24423A")),           # RevK
    (SiliconId(0b0000_1000, 0b1011_0001), PartNumberMatcher("CY8C23533")),            # RevK
    (SiliconId(0b0000_1000, 0b1011_0000), PartNumberMatcher("CY8C23433")),            # RevK
    (SiliconId(0b0000_1000, 0b1011_0010), PartNumberMatcher("CY8C23033")),            # RevK
    (SiliconId(0b0000_0000, 0b0001_0111), PartNumberMatcher("CY8C21123")),            # RevK
    (SiliconId(0b0000_0000, 0b0001_1000), PartNumberMatcher("CY8C21223")),            # RevK
    (SiliconId(0b0000_0000, 0b0001_1001), PartNumberMatcher("CY8C21323")),            # RevK
    (SiliconId(0b0000_0000, 0b0011_0110), PartNumberMatcher("CY8C21234")),            # RevK
    (SiliconId(0b0000_1000, 0b0011_0111), PartNumberMatcher("CY8C21312")),            # RevK
    (SiliconId(0b0000_0000, 0b0011_0111), PartNumberMatcher("CY8C21334")),            # RevK
    (SiliconId(0b0000_0000, 0b0011_0111), PartNumberMatcher("CY8C21334W")),           # RevK
    (SiliconId(0b0000_0000, 0b0011_1000), PartNumberMatcher("CY8C21434")),            # RevK
    (SiliconId(0b0000_1000, 0b0100_0000), PartNumberMatcher("CY8C21512")),            # RevK
    (SiliconId(0b0000_0000, 0b0100_0000), PartNumberMatcher("CY8C21534")),            # RevK
    (SiliconId(0b0000_0000, 0b0100_0000), PartNumberMatcher("CY8C21534W")),           # RevK
    (SiliconId(0b0000_0000, 0b0100_1001), PartNumberMatcher("CY8C21634")),            # RevK
    (SiliconId(0b0000_0111, 0b0011_1000), PartNumberMatcher("CY8CTMG110-32LTXI")),    # RevK
    (SiliconId(0b0000_0111, 0b0011_1001), PartNumberMatcher("CY8CTMG110-00PVXI")),    # RevK
    (SiliconId(0b0000_0110, 0b0011_1000), PartNumberMatcher("CY8CTST110-32LTXI")),    # RevK
    (SiliconId(0b0000_0110, 0b0011_1001), PartNumberMatcher("CY8CTST110-00PVXI")),    # RevK

    (SiliconId(0b0000_0000, 0b1101_0011), PartNumberMatcher("CY8C21345")),            # RevL
    (SiliconId(0b0000_1000, 0b1101_1010), PartNumberMatcher("CY8C21645-24xxXA")),     # RevL
    (SiliconId(0b0000_1000, 0b1101_1001), PartNumberMatcher("CY8C21645-12xxXE")),     # RevL
    (SiliconId(0b0000_0000, 0b1101_0001), PartNumberMatcher("CY8C22345")),            # RevL
    (SiliconId(0b0000_1100, 0b1101_0001), PartNumberMatcher("CY8C22345H-24xxXA")),    # RevL
    (SiliconId(0b0000_0000, 0b1101_0010), PartNumberMatcher("CY8C22545-24xxXI")),     # RevL
    (SiliconId(0b0000_0000, 0b1101_1010), PartNumberMatcher("CY8C22645-24xxXA")),     # RevL
    (SiliconId(0b0000_0000, 0b1101_1001), PartNumberMatcher("CY8C22645-12xxXE")),     # RevL
    (SiliconId(0b0000_0000, 0b0001_1101), PartNumberMatcher("CY8C24794")),            # RevL
    (SiliconId(0b0000_0000, 0b0001_1111), PartNumberMatcher("CY8C24894")),            # RevL
    (SiliconId(0b0000_0000, 0b0101_1001), PartNumberMatcher("CY8C24994")),            # RevL
    (SiliconId(0b0000_0000, 0b1110_0000), PartNumberMatcher("CY8C28000")),            # RevL
    (SiliconId(0b0000_0000, 0b1110_0001), PartNumberMatcher("CY8C28445")),            # RevL
    (SiliconId(0b0000_0000, 0b1110_0010), PartNumberMatcher("CY8C28545")),            # RevL
    (SiliconId(0b0000_0000, 0b1110_0011), PartNumberMatcher("CY8C28645")),            # RevL
    (SiliconId(0b0000_0000, 0b1110_0100), PartNumberMatcher("CY8C28243")),            # RevL
    (SiliconId(0b0000_0000, 0b1110_1010), PartNumberMatcher("CY8C28643")),            # RevL
    (SiliconId(0b0000_0000, 0b1110_0101), PartNumberMatcher("CY8C28452")),            # RevL
    (SiliconId(0b0000_0000, 0b1110_0110), PartNumberMatcher("CY8C28413")),            # RevL
    (SiliconId(0b0000_0000, 0b1110_1011), PartNumberMatcher("CY8C28513")),            # RevL
    (SiliconId(0b0000_0000, 0b1110_0111), PartNumberMatcher("CY8C28433")),            # RevL
    (SiliconId(0b0000_0000, 0b1110_1100), PartNumberMatcher("CY8C28533")),            # RevL
    (SiliconId(0b0000_0000, 0b1110_1000), PartNumberMatcher("CY8C28403")),            # RevL
    (SiliconId(0b0000_0000, 0b1110_1001), PartNumberMatcher("CY8C28623")),            # RevL
    (SiliconId(0b0000_0000, 0b0010_1010), PartNumberMatcher("CY8C29466")),            # RevL
    (SiliconId(0b0000_0000, 0b0010_1011), PartNumberMatcher("CY8C29566")),            # RevL
    (SiliconId(0b0000_0000, 0b0010_1100), PartNumberMatcher("CY8C29666")),            # RevL
    (SiliconId(0b0000_0000, 0b0010_1101), PartNumberMatcher("CY8C29866")),            # RevL
    (SiliconId(0b0000_0110, 0b0001_1111), PartNumberMatcher("CY8CTST120-56")),        # RevL
    (SiliconId(0b0000_0110, 0b0001_1011), PartNumberMatcher("CY8CTST120-00")),        # RevL
    (SiliconId(0b0000_0101, 0b0001_1111), PartNumberMatcher("CY8CTMA120-56")),        # RevL
    (SiliconId(0b0000_0101, 0b0001_1011), PartNumberMatcher("CY8CTMA120-00")),        # RevL
    (SiliconId(0b0000_0101, 0b0101_1001), PartNumberMatcher("CY8CTMA120-100")),       # RevL
    (SiliconId(0b0000_0111, 0b0001_1111), PartNumberMatcher("CY8CTMG120-56")),        # RevL
    (SiliconId(0b0000_0111, 0b0001_1011), PartNumberMatcher("CY8CTMG120-00")),        # RevL
    (SiliconId(0b0000_0000, 0b0001_1110), PartNumberMatcher("CY7C64215-28")),         # RevL
    (SiliconId(0b0000_0000, 0b0101_0011), PartNumberMatcher("CY7C64215-56")),         # RevL

    (SiliconId(0b0000_0000, 0b1001_1010, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20066", "CY8C20066A")),                 # RevI
    (SiliconId(0b0000_0000, 0b1011_0011, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20236", "CY8C20236A")),                 # RevI
    (SiliconId(0b0000_0000, 0b1010_1010, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20246", "CY8C20246A")),                 # RevI
    (SiliconId(0b0000_0000, 0b1001_0110, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20266", "CY8C20266A")),                 # RevI
    (SiliconId(0b0000_0000, 0b1011_0100, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20336", "CY8C20336A")),                 # RevI
    (SiliconId(0b0000_1100, 0b1011_0100, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20336H-24LQXI")),                       # RevI
    (SiliconId(0b0000_0000, 0b1010_1100, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20346", "CY8C20346A")),                 # RevI
    (SiliconId(0b0000_1100, 0b1010_1100, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20346H-24LQXI")),                       # RevI
    (SiliconId(0b0000_0000, 0b1001_0111, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20366", "CY8C20366A")),                 # RevI
    (SiliconId(0b0000_0000, 0b1010_1111, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20396", "CY8C20396A")),                 # RevI
    (SiliconId(0b0000_0000, 0b1011_0101, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20436", "CY8C20436A")),                 # RevI
    (SiliconId(0b0000_0000, 0b1010_1101, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20446 CY8C20446A")),                    # RevI
    (SiliconId(0b0000_1100, 0b1010_1101, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20446H-24LQXI")),                       # RevI
    (SiliconId(0b0000_0000, 0b1001_1000, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20466", "CY8C20466A")),                 # RevI
    (SiliconId(0b0000_0000, 0b1011_1101, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20496", "CY8C20496A")),                 # RevI
    (SiliconId(0b0000_0000, 0b1011_1001, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20536", "CY8C20536A")),                 # RevI
    (SiliconId(0b0000_0000, 0b1010_1110, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20546", "CY8C20546A")),                 # RevI
    (SiliconId(0b0000_0000, 0b1001_1001, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20566", "CY8C20566A")),                 # RevI
    (SiliconId(0b0000_0000, 0b1011_1010, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20636", "CY8C20636A")),                 # RevI
    (SiliconId(0b0000_0000, 0b1011_1000, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20646", "CY8C20646A")),                 # RevI
    (SiliconId(0b0000_0000, 0b1001_1100, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20666", "CY8C20666A")),                 # RevI
    (SiliconId(0b0000_0000, 0b1011_1110, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20746A")),                              # RevI
    (SiliconId(0b0000_0000, 0b1011_1111, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20766A")),                              # RevI
    (SiliconId(0b0000_0000, 0b1010_1011, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY7C60400")),                               # RevI
    (SiliconId(0b0000_0000, 0b1011_0110, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY7C60413")),                               # RevI
    (SiliconId(0b0000_0000, 0b1010_0111, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY7C60445")),                               # RevI
    (SiliconId(0b0000_0000, 0b1010_1000, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY7C60455")),                               # RevI
    (SiliconId(0b0000_0000, 0b1010_1001, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY7C60456")),                               # RevI
    (SiliconId(0b0000_0000, 0b1010_0110, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY7C64300")),                               # RevI
    (SiliconId(0b0000_0000, 0b1010_0000, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY7C64315")),                               # RevI
    (SiliconId(0b0000_0000, 0b1010_0001, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY7C64316")),                               # RevI
    (SiliconId(0b0000_0000, 0b1011_0111, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY7C64343")),                               # RevI
    (SiliconId(0b0000_0000, 0b1010_0010, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY7C64345")),                               # RevI
    (SiliconId(0b0000_0000, 0b1010_0011, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY7C64355")),                               # RevI
    (SiliconId(0b0000_0000, 0b1010_0100, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY7C64356")),                               # RevI
    (SiliconId(0b0000_0111, 0b1001_1010, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTMG200-00LTXI", "CY8CTMG200A-00LTXI")), # RevI
    (SiliconId(0b0000_0111, 0b0110_1100, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTMG200-16LGXI", "CY8CTMG200A-16LGXI")), # RevI
    (SiliconId(0b0000_0111, 0b0110_1101, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTMG200-24LQXI", "CY8CTMG200A-24LQXI")), # RevI
    (SiliconId(0b0000_0111, 0b0110_1110, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTMG200-32LQXI", "CY8CTMG200A-32LQXI")), # RevI
    (SiliconId(0b0000_0111, 0b0110_1111, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTMG200-48LTXI", "CY8CTMG200A-48LTXI")), # RevI
    (SiliconId(0b0000_1111, 0b0110_1111, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTMG200AH-48LTXI")),                     # RevI
    (SiliconId(0b0000_0111, 0b1101_0100, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTMG240-LQI-01")),                       # RevI
    (SiliconId(0b0000_0111, 0b1101_0101, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTMG240-LTI-01")),                       # RevI
    (SiliconId(0b0000_0111, 0b1011_1111, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CP8CTMG240-FNC-01")),                       # RevI
    (SiliconId(0b0000_0111, 0b0001_1100, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTMG200-48PVXI", "CY8CTMG200A-48PVXI")), # RevI
    (SiliconId(0b0000_0110, 0b0110_1100, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTST200-16LGXI", "CY8CTST200A-16LGXI")), # RevI
    (SiliconId(0b0000_0110, 0b0110_1101, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTST200-24LQXI", "CY8CTST200A-24LQXI")), # RevI
    (SiliconId(0b0000_0110, 0b0110_1110, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTST200-32LQXI", "CY8CTST200A-32LQXI")), # RevI
    (SiliconId(0b0000_0110, 0b0110_1111, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTST200-48LTXI", "CY8CTST200A-48LTXI")), # RevI
    (SiliconId(0b0000_0110, 0b0001_1100, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTST200-48PVXI", "CY8CTST200A-48PVXI")), # RevI
    (SiliconId(0b0000_0110, 0b1101_0110, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTST241-LQI-01")),                       # RevI
    (SiliconId(0b0000_0110, 0b1101_0111, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTST241-LTI-01")),                       # RevI
    (SiliconId(0b0000_0110, 0b1011_1111, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CP8CTST241-FNC-01")),                       # RevI
    (SiliconId(0b0000_0111, 0b0110_0001, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTMG201-16LQXI")),                       # RevI
    (SiliconId(0b0000_0111, 0b0110_0010, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTMG201-24LQXI")),                       # RevI
    (SiliconId(0b0000_0111, 0b0110_0011, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTMG201-32LQXI")),                       # RevI
    (SiliconId(0b0000_0111, 0b0110_0100, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTMG201-48LTXI", "CY8CTMG201A-48LTXI")), # RevI
    (SiliconId(0b0000_0111, 0b0110_0101, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTMG201-48PVXI", "CY8CTMG201A-48PVXI")), # RevI
    (SiliconId(0b0000_0110, 0b1011_1110, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CP8CTST242-FNC-01")),                       # RevI
    (SiliconId(0b0000_1011, 0b1010_1010, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20246AS-24LKXI")),                      # RevI
    (SiliconId(0b0000_0000, 0b1101_1011, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20336AN-24LQXI")),                      # RevI
    (SiliconId(0b0000_1011, 0b1010_1100, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20346AS-24LQXI")),                      # RevI
    (SiliconId(0b0000_0000, 0b1101_1100, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20436AN-24LQXI")),                      # RevI
    (SiliconId(0b0000_1011, 0b1010_1101, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20446AS-24LQXI")),                      # RevI
    (SiliconId(0b0000_0011, 0b1010_1101, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20446L-24LQXI")),                       # RevI
    (SiliconId(0b0000_1011, 0b1001_1000, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20466AS-24LQXI")),                      # RevI
    (SiliconId(0b0000_0011, 0b1001_1000, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20466L-24LQXI")),                       # RevI
    (SiliconId(0b0000_0011, 0b1011_1101, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20496L-24LQXI")),                       # RevI
    (SiliconId(0b0000_0011, 0b1010_1110, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20546L-24PVXI")),                       # RevI
    (SiliconId(0b0000_0011, 0b1001_1001, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20566L-24PVXI")),                       # RevI
    (SiliconId(0b0000_0000, 0b1101_1000, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20636AN-24LTXI")),                      # RevI
    (SiliconId(0b0000_1011, 0b1011_1000, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20646AS-24LQXI")),                      # RevI
    (SiliconId(0b0000_1011, 0b1011_1000, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20646AS-24LTXI")),                      # RevI
    (SiliconId(0b0000_0011, 0b1011_1000, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20646L-24LTXI", "CY8C20646L-24LQXI")),  # RevI
    (SiliconId(0b0000_1011, 0b1001_1100, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20666AS-24LQXI")),                      # RevI
    (SiliconId(0b0000_1011, 0b1001_1100, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20666AS-24LTXI")),                      # RevI
    (SiliconId(0b0000_0011, 0b1001_1100, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20666L-24LTXI CY8C20666L-24LQXI")),     # RevI
    (SiliconId(0b0000_0111, 0b0110_0001, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTMG201-16LGXI")),                       # RevI
    (SiliconId(0b0000_0111, 0b0110_0010, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTMG201-24LQXI")),                       # RevI
    (SiliconId(0b0000_0110, 0b0110_0001, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTST201-16LGXI")),                       # RevI
    (SiliconId(0b0000_0110, 0b0110_0010, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTST201-24LQXI")),                       # RevI
    (SiliconId(0b0000_0110, 0b0110_0011, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTST201-32LQXI")),                       # RevI
    (SiliconId(0b0000_0110, 0b0110_0100, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTST201-48LTXI")),                       # RevI
    (SiliconId(0b0000_0110, 0b0110_0101, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTST201-48PVXI")),                       # RevI
    (SiliconId(0b0000_0110, 0b1001_1000, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTST242-LQI-01")),                       # RevI
    (SiliconId(0b0000_0110, 0b1001_1100, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8CTST242-LTI-01")),                       # RevI
    (SiliconId(0b0000_0001, 0b0100_0010, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20237-24LKXI")),                        # RevI
    (SiliconId(0b0000_0001, 0b0100_0000, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20237-24SXI")),                         # RevI
    (SiliconId(0b0000_0001, 0b0100_0011, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20247-24LKXI")),                        # RevI
    (SiliconId(0b0000_1011, 0b0100_0011, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20247S-24LKXI")),                       # RevI
    (SiliconId(0b0000_0001, 0b0100_0001, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20247-24SXI")),                         # RevI
    (SiliconId(0b0000_0001, 0b0100_0100, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20337-24LQXI")),                        # RevI
    (SiliconId(0b0000_0001, 0b0101_0000, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20337AN-24LQXI")),                      # RevI
    (SiliconId(0b0000_0001, 0b0100_0101, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20347-24LQXI")),                        # RevI
    (SiliconId(0b0000_1011, 0b0100_0101, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20347S-24LQXI")),                       # RevI
    (SiliconId(0b0000_0001, 0b0100_0110, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20437-24LQXI")),                        # RevI
    (SiliconId(0b0000_0001, 0b0101_0001, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20437AN-24LQXI")),                      # RevI
    (SiliconId(0b0000_0001, 0b0100_0111, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20447-24LQXI")),                        # RevI
    (SiliconId(0b0000_1011, 0b0100_0111, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20447S-24LQXI")),                       # RevI
    (SiliconId(0b0000_0001, 0b0100_1000, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20467-24LQXI")),                        # RevI
    (SiliconId(0b0000_1011, 0b0100_1000, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20467S-24LQXI")),                       # RevI
    (SiliconId(0b0000_0001, 0b0100_1001, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20637-24LQXI")),                        # RevI
    (SiliconId(0b0000_0001, 0b0100_1111, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20637AN-24LQXI")),                      # RevI
    (SiliconId(0b0000_0001, 0b0100_1010, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20647-24LQXI")),                        # RevI
    (SiliconId(0b0000_1011, 0b0100_1010, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20647S-24LQXI")),                       # RevI
    (SiliconId(0b0000_0001, 0b0100_1011, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20667-24LQXI")),                        # RevI
    (SiliconId(0b0000_1011, 0b0100_1011, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20667S-24LQXI")),                       # RevI
    (SiliconId(0b0000_0001, 0b0100_1100, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20747-24FDXC")),                        # RevI
    (SiliconId(0b0000_0001, 0b0100_1101, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20767-24FDXC")),                        # RevI
    (SiliconId(0b0000_0001, 0b1010_0101, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20045-24LKXI")),                        # RevI
    (SiliconId(0b0000_0001, 0b0111_0000, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20055-24LKXI")),                        # RevI
    (SiliconId(0b0000_0001, 0b1100_1110, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C20055-24SXI")),                         # RevI

    (SiliconId(0b0000_0000, 0b1111_0111, 0b0101_0010, 0b0010_0001), PartNumberMatcher("CY8C24493")), # Not documented, but found experimentally
}

def get_expected_silicon_id(lookup_part_number):
    for sid, part in silicon_ids:
        if part.fullmatch(lookup_part_number):
            return sid
    return None

class RegexLookup:
    def __init__(self, dictionary):
        self.dictionary = dictionary

    def __getitem__(self, item):
        for r in self.dictionary:
            if r.fullmatch(item):
                return self.dictionary[r]
        return None

PROGRAM_BLOCK = {
    0: # RevK, RevL
        "10011111100010101001111001111111001010110111" +
        "11011110111000000001111101111011000000000111" +
        "10011111000001110101111001111100100000011111" +
        "11011110101000000001111101111010000000011111" +
        "10011111011100000001111101111100100110000111" +
        "11011111010010000001111101111000000000010111" +
        "11011111000000000001111101111111100010010111",
    1: # RevK
        "10011111100000101011111001111111001010110111" +
        "11011110111000000001111101111011000000000111" +
        "10011111000001110101111001111100100000011111" +
        "11011110101000000001111101111010000000011111" +
        "10011111011100000001111101111100100110000111" +
        "11011111010010000001111101111000000000010111" +
        "11011111000000000001111101111111100010010111",
    2: # PROGRAM-AND-VERIFY , matches ISSP Specs: RevI
        "110111101110001000011111011111110000001001111101110001000000100111" +
        "110111000000000001111110011111000001110101111001111100100000011111" +
        "100111110111000000011111011111110000000001111101110001000000000111" +
        "110111000000000001111111011110111000000001111101101010000000001111" +
        "110111101000000001111111011110101000000001111101111011000000000111" +
        "110111100000000101011111011111000000000001111101111100101000000111" +
        "11011111010001100001111101111111100010010110",
}

# Notes:
# * banks=0 implies it isn't documented as having the concept of banks, so don't try to set bank number
# * read_security_type=0 implies that reading security is definitely not supported so print an error
# * read_security_type=1 implies that reading security (with same as type 2 commands) may or may not be
#          supported, so perhaps print a warning. Some devices documented in the RevK ISSP spec have
#          been found as supporting this command, even though it's not documented there.
# * read_security_type=2 use the VERIFY-SECURE-SETUP vectors documented in RevL ISSP spec.
# * read_security_type=3 use the various security-reading vectors documented in RevI ISSP specs.
# * read_security_type=4 uses the same security-reading vectors documented in RevI ISSP specs,
#          however it doesn't do wait-and-poll after READ-SECURITY-2/READ-SECURITY-3, like Figure 2-12
#          describes. Doing a WAIT-AND_POLL has been observed to not work correctly on a CY8C24493 device.
#          However reading security values does work correctly if we skip polling for SDATA. We're going
#          to assume that the spec has a mistake in it in this regard, and all devices covered by the
#          spec behave like this. If you find a device that is covered by the RevI spec, that has issues
#          reading the security, bytes, please consider trying read_security_type=3, and update this
#          comment. in the meantime all RevI devices will be configured with trying read_security_type=4
# * needs_single_clock_pulse_for_poll = 1 means exactly 1 SCLK cycle is needed after a vector that requires
#          polling (and after SDATA has settled low), to allow SDATA to go high.
# * needs_arbitrary_clocks_for_poll = 1 means we are following the textual specification of WAIT-AND-POLL
#          from RevI specs, which says clocking is necessary for SDATA to go high. Setting this bit high
#          will generate as many clock pulses as necessary, and it will stop generating clock pulses as soon
#          as SDATA goes high.
# * needs_single_clock_pulse_for_poll = 0, and needs_arbitrary_clocks_for_poll = 0 at the same time appears
#          to match Figure 2-4 from RevI specs, however this combination has been observed to not work
#          correctly on a CY8C24493 device. Since the spec is self-contradictory we are assuming there is a
#          mistake in the spec, and we are configuring all RevI-covered devices with
#          needs_arbitrary_clocks_for_poll = 1. If you are having initialization issues with RevI
#          devices, please consider playing with these settings.
# * secure_bytes_per_bank refers to the number of bytes we should read/write, not to the number of bytes
#          containing useful security data.
# * erase_block_type=0 means not supported/not implemented
# * erase_block_type=1 means use the vector described in RevK/RevL specs

FlashConfig = namedtuple("FlashConfig",
    " ".join(reversed([
        'erase_block_type', #----------------------------------------------------------------------------------+
        'read_security_type', #-----------------------------------------------------------------------------+  |
        'set_security_type', #---------------------------------------------------------------------------+  |  |
        'verify_setup_type', #------------------------------------------------------------------------+  |  |  |
        'has_read_status', #-----------------------------------------------------------------------+  |  |  |  |
        'has_read_write_setup', #---------------------------------------------------------------+  |  |  |  |  |
        'erase_type', #----------------------------------------------------------------------+  |  |  |  |  |  |
        'has_sync_en_dis_cmd', #----------------------------------------------------------+  |  |  |  |  |  |  |
        'init_type', #-----------------------------------------------------------------+  |  |  |  |  |  |  |  |
        'needs_arbitrary_clocks_for_poll', #----------------------------------------+  |  |  |  |  |  |  |  |  |
        'needs_single_clock_pulse_for_poll', #-----------------------------------+  |  |  |  |  |  |  |  |  |  |
        'checksum_setup_type', #----------------------------------------------+  |  |  |  |  |  |  |  |  |  |  |
        'program_block_type', #--------------------------------------------+  |  |  |  |  |  |  |  |  |  |  |  |
        'secure_bytes_per_bank', #--------------------------------------+  |  |  |  |  |  |  |  |  |  |  |  |  |
        'banks', #--------------------------------------------------+   |  |  |  |  |  |  |  |  |  |  |  |  |  |
        'blocks', #----------------------------------------------+  |   |  |  |  |  |  |  |  |  |  |  |  |  |  |
        'bytes_per_block', #--------------------------------+    |  |   |  |  |  |  |  |  |  |  |  |  |  |  |  |
    ])))  #                                                 |    |  |   |  |  |  |  |  |  |  |  |  |  |  |  |  |
          #                                                 |    |  |   |  |  |  |  |  |  |  |  |  |  |  |  |  |
flash_config = RegexLookup({ #                              |    |  |   |  |  |  |  V  |  |  |  |  |  |  |  |  |
    PartNumberMatcher("CY8C21x12"):           FlashConfig( 64, 128, 0, 64, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1), # RevK # 512 bytes SRAM
    PartNumberMatcher("CY8C21x23"):           FlashConfig( 64,  64, 0, 64, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1), # RevK # 256 bytes SRAM
    PartNumberMatcher("CY8C21x34"):           FlashConfig( 64, 128, 0, 64, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1), # RevK # 512 bytes SRAM
    PartNumberMatcher("CY8C23x33"):           FlashConfig( 64, 128, 0, 64, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1), # RevK # 256 bytes SRAM

    PartNumberMatcher("CY8C24x23A"):          FlashConfig( 64,  64, 0, 64, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1), # RevK # 256 bytes SRAM
    PartNumberMatcher("CY8C27x43"):           FlashConfig( 64, 256, 0, 64, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1), # RevK # 256 bytes SRAM
    # TODO the assimetry between program_block_type/checksum_setup_type for the above two devices is strange. I think I have one of
    # these two devices, check if it works okay. If it does, remove comment.

    PartNumberMatcher("CY8CTMG110"):          FlashConfig( 64, 128, 0, 64, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1), # RevK # 512 bytes SRAM
    PartNumberMatcher("CY8CTST110"):          FlashConfig( 64, 128, 0, 64, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1), # RevK # 512 bytes SRAM

    PartNumberMatcher("CY8C22x45"):           FlashConfig( 64, 128, 2, 32, 0, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 2, 1), # RevL # 1K SRAM
    PartNumberMatcher("CY8C22x45H"):          FlashConfig( 64, 128, 2, 32, 0, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 2, 1), # RevL # 1K SRAM
    PartNumberMatcher("CY8C24x94"):           FlashConfig( 64, 128, 2, 32, 0, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 2, 1), # RevL # 1K SRAM
    PartNumberMatcher("CY8C28xxx"):           FlashConfig( 64, 128, 2, 32, 0, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 2, 1), # RevL # 1K SRAM
    PartNumberMatcher("CY8CTST120"):          FlashConfig( 64, 128, 2, 32, 0, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 2, 1), # RevL # 1K SRAM
    PartNumberMatcher("CY8CTMA120"):          FlashConfig( 64, 128, 2, 32, 0, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 2, 1), # RevL # 1K SRAM
    PartNumberMatcher("CY8CTMG120"):          FlashConfig( 64, 128, 2, 32, 0, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 2, 1), # RevL # 1K SRAM
    PartNumberMatcher("CY7C64215"):           FlashConfig( 64, 128, 2, 32, 0, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 2, 1), # RevL # 1K SRAM
    PartNumberMatcher("CY8C29x66"):           FlashConfig( 64, 128, 4, 32, 0, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 2, 1), # RevL # 2K SRAM
    PartNumberMatcher("CY8C21x45"):           FlashConfig( 64, 128, 1, 32, 0, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 2, 1), # RevL # 512 bytes SRAM

    PartNumberMatcher("CY7C60400"):           FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY7C60413"):           FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY7C60445"):           FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY7C60455"):           FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY7C60456"):           FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY7C64300"):           FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY7C64313"):           FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY7C64315"):           FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY7C64316"):           FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY7C64343"):           FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY7C64345"):           FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY7C64355"):           FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY7C64356"):           FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20045-24LKXI"):    FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20055-24LKXI"):    FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20055-24SXI"):     FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20066"):           FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20236-24LKXI"):    FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20246-24LKXI"):    FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20266-24LKXI"):    FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20336-24LQXI"):    FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20336H-24LQXI"):   FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20346-24LQXI"):    FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20346H-24LQXI"):   FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20366-24LQXI"):    FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20396-24LQXI"):    FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20436-24LQXI"):    FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20446-24LQXI"):    FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20446H-24LQXI"):   FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20466-24LQXI"):    FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20496-24LQXI"):    FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20536-24PVXI"):    FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20546-24PVXI"):    FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20566-24PVXI"):    FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20636-24LQXI"):    FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20646-24LQXI"):    FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20666-24LQXI"):    FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTST200-16LGXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTST200-24LQXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTST200-32LQXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTST200-48LTXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTST200-48PVXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTMG200-00LGXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTMG200-16LGXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTMG200-24LQXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTMG200-32LQXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTMG200-48LTXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTMG200-48PVXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTMG201-32LQXI"):   FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTMG201-48LTXI"):   FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTMG201-48PVXI"):   FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20066A"):          FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20236A-24LKXI"):   FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20246A-24LKXI"):   FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20246AS-24LKXI"):  FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20266A-24LKXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20336A-24LQXI"):   FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20336AN-24LQXI"):  FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20346A-24LQXI"):   FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20346AS-24LQXI"):  FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20366A-24LQXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20396A-24LQXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20436A-24LQXI"):   FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20436AN-24LQXI"):  FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20446A-24LQXI"):   FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20446AS-24LQXI"):  FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20446L-24LQXI"):   FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20466A-24LQXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20466AS-24LQXI"):  FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20466L-24LQXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20496A-24LQXI"):   FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20496L-24LQXI"):   FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20536A-24PVXI"):   FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20546A-24PVXI"):   FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20546L-24PVXI"):   FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20566A-24PVXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20566L-24PVXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20636A-24LTXI"):   FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20636A-24LQXI"):   FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20636AN-24LTXI"):  FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20646A-24LTXI"):   FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20646A-24LQXI"):   FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20646AS-24LTXI"):  FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20646L-24LTXI"):   FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20646L-24LQXI"):   FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20666A-24LTXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20666A-24LQXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20666AS-24LTXI"):  FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20666L-24LTXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20666L-24LQXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20746A-24FDXC"):   FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20766A-24FDXC"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTST200A-16LGXI"):  FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTST200A-24LQXI"):  FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTST200A-32LQXI"):  FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTST200A-48LTXI"):  FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTST200A-48PVXI"):  FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTST241-LQI-01"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTST241-LTI-01"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CP8CTST241-FNC-01"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTMG200A-00LGXI"):  FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTMG200A-16LGXI"):  FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTMG200A-24LQXI"):  FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTMG200A-32LQXI"):  FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTMG200A-48LTXI"):  FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTMG200AH-48LTXI"): FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTMG200A-48PVXI"):  FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTMG201A-32LQXI"):  FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTMG201A-48LTXI"):  FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTMG201A-48PVXI"):  FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTMG240-LQI-01"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8CTMG240-LTI-01"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CP8CTMG240-FNC-01"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20237-24SXI"):     FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20247-24SXI"):     FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20237-24LKXI"):    FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20247-24LKXI"):    FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20247S-24LKXI"):   FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20337-24LQXI"):    FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20337AN-24LQXI"):  FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20347-24LQXI"):    FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20347S-24LQXI"):   FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20437-24LQXI"):    FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20437AN-24LQXI"):  FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20447-24LQXI"):    FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20447S-24LQXI"):   FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20467-24LQXI"):    FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20467S-24LQXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20637-24LQXI"):    FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20637AN-24LQXI"):  FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20647-24LQXI"):    FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20647S-24LQXI"):   FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20667-24LQXI"):    FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20667S-24LQXI"):   FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20747-24FDXC"):    FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C20767-24FDXC"):    FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI

    # The CY8C24X93 datasheet points towards the AN2026C document, aka RevI, so this device must use the same
    # vectors as other devices from RevI. Flash configuration has been deduced from the TRM:
    PartNumberMatcher("CY8C24493"):           FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C24693"):           FlashConfig(128, 256, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C24593"):           FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C24393"):           FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C24293"):           FlashConfig(128, 128, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C24193"):           FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
    PartNumberMatcher("CY8C24093"):           FlashConfig(128,  64, 0, 64, 2, 3, 0, 1, 1, 1, 1, 1, 1, 1, 1, 4, 0), # RevI
})

VERIFY_SETUP = {
    0: ( # Matches ISSP Specs: RevK, RevL
        "11011110111000000001111101111011000000000111" +
        "10011111000001110101111001111100100000011111" +
        "11011110101000000001111101111010000000011111" +
        "10011111011100000001111101111100100110000111" +
        "11011111010010000001111101111000000000001111" +
        "11011111000000000001111101111111100010010111"),
    1: ( # RevI
        "110111101110001000011111011111110000001001111101110001000000100111" +
        "110111000000000001111110011111000001110101111001111100100000011111" +
        "100111110111000000011111011111110000000001111101110001000000000111" +
        "110111000000000001111111011110111000000001111101101010100000001111" +
        "110111101000000001111111011110101000000001111101111011000000000111" +
        "110111100000000000111111011111000000000001111101111100101000000111" +
        "11011111010001100001111101111111100010010110"),
}

# Documented in RevL ISSP Specification v13_00 only,
# not clear if all devices support it:
GET_SECURITY = ( # a.k.a. "VERIFY-SECURE-SETUP"
    "11011110111000000001111101111011000000000111" +
    "10011111000001110101111001111100100000011111" +
    "10011111101000000001111001111111100000000111" +
    "11011110101000000001111101111010000000011111" +
    "10011111011100000001111101111100100110000111" +
    "11011111010010000001111101111000000010000111" +
    "11011111000000000001111101111111100010010111")

READ_SECURITY_SETUP = ( # RevI
    "110111101110001000011111011000001000100001111101100001000010000111" +
    "1101111011100000000111")

READ_SECURITY_1 = ( # RevI
    "110111101110001000011111011100101000011101111101110010100000000111" +
    "110111001010aaaaaaa1111101110010100000000111")

READ_SECURITY_2 = ( # RevI
    "110111101110000000011111011110100000000111111101111010100000000111" +
    "110111101100000000011111011111000010111011111101111100111100101111" +
    "110111110100011000011111011110111000100001111101111111100010010110")

READ_SECURITY_3 = ( # RevI
    "110111101110000000011111011110100000000111111101111010100000000111" +
    "11011110110000000001111101111100001010011111110111110011aaaaaaa111" +
    "11011111010001100001111101111111100010010110")

SET_SECURITY = { # a.k.a. "SECURE"
    0: ( # Matches ISSP Specs: RevK, RevL
        "10011111100010101001111001111111001010110111" +
        "11011110111000000001111101111011000000000111" +
        "10011111000001110101111001111100100000011111" +
        "11011110101000000001111101111010000000011111" +
        "10011111011100000001111101111100100110000111" +
        "11011111010010000001111101111000000000100111" +
        "11011111000000000001111101111111100010010111"),
    1: ( # RevI
        "110111101110001000011111011111110000001001111101110001000000100111" +
        "110111000000000001111110011111000001110101111001111100100000011111" +
        "100111110111000000011111011111110000000001111101110001000000000111" +
        "110111000000000001111111011110111000000001111101101010000000001111" +
        "110111101000000001111111011110101000000001111101111011000000000111" +
        "110111100000000010011111011111000000000001111101111100101000000111" +
        "11011111010001100001111101111111100010010110"),
}

CHECKSUM_SETUP = {
    0: # RevK
        "11011110111000000001111101111011000000000111" +
        "10011111000001110101111001111100100000011111" +
        "11011110101000000001111101111010000000011111" +
        "10011111011100000001111101111100100110000111" +
        "11011111010010000001111001111101000000000111" +
        "11011110000000001111111101111100000000000111" +
        "1101111111100010010111",
    1: # RevK
        "11011110111000000001111101111011000000000111" +
        "10011111000001110101111001111100100000011111" +
        "11011110101000000001111101111010000000011111" +
        "10011111011100000001111101111100100110000111" +
        "11011111010010000001111001111101001000000111" +
        "11011110000000001111111101111100000000000111" +
        "1101111111100010010111",
    2: # RevL
        "11011110111000000001111101111011000000000111" +
        "10011111000001110101111001111100100000011111" +
        "11011110101000000001111101111010000000011111" +
        "10011111011000000001111101111100100110000111" +
        "11011111010010000001111001111101010000000111" +
        "11011110000000001111111101111100000000000111" +
        "1101111111100010010111",
    3: # RevI
        "110111101110001000011111011111110000001001111101110001000000100111" +
        "110111000000000001111110011111000001110101111001111100100000011111" +
        "100111110100000000011111011111110000000001111101110001000000000111" +
        "110111000000000001111111011110111000000001111101111010000000011111" +
        "110111101010000000011111011110110000000001111101111000000000111111" +
        "110111110000000000011111011111001010000001111101111101000110000111" +
        "1101111111100010010110",
}

READ_WRITE_SETUP = ( # RevI
    "110111101111000000011111011110000000000001111101101000000000001111")

ERASE_BLOCK = ( # RevK, RevL
    "10011111100010101001111001111111001010110111" +
    "11011110111000000001111101111011000000000111" +
    "10011111000001110101111001111100100000011111" +
    "11011110101000000001111101111010000000011111" +
    "11011111001001100001111101111101001000000111" +
    "11011110000000000111111101111100000000000111"
    "1101111111100010010111")
