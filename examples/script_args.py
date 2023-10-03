import argparse

parser = argparse.ArgumentParser('script_args.py')
parser.add_argument('-m', '--my-arg', default=0, type=int)

my_args = parser.parse_args(args.script_args)

print(my_args)
