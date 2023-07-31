def num_to_si(num, long_prefix=False):
    prefixes = [
        (  3, 'G', 'Giga'  ),
        (  2, 'M', 'Mega'  ),
        (  1, 'k', 'Kilo'  ),
        (  0, '',  ''      ),
        ( -1, 'm', 'mili'  ),
        ( -2, 'u', 'micro' ),
        ( -3, 'n', 'nano'  ),
    ]
    try:
        factor, tshort, tlong = next(filter(lambda x: num >= (1000 ** x[0]), prefixes))
    except StopIteration:
        factor, tshort, tlong = prefixes[-1]
    prefix = tlong if long_prefix else tshort
    return num * (1000 ** -factor), prefix
