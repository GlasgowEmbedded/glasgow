import sys
from fx2.format import input_data, output_data


def normalize(input):
    output = []
    for (addr, chunk) in sorted(input):
        if output and output[-1][0] + len(output[-1][1]) == addr:
            output[-1] = (output[-1][0], output[-1][1] + chunk)
        else:
            output.append((addr, chunk))
    return output


with open(sys.argv[1], "rb") as f:
    data = input_data(f)
data = normalize(data)
with open(sys.argv[2], "wb") as f:
    output_data(f, data)
