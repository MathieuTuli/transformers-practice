"""
@author: Mathieu Tuli
@github: MathieuTuli
@email: tuli.mathie@gmail.com
"""
from configargparse import Namespace

from onmt.bin.train import train as onmt_train


def main(args: Namespace):
    if args.framework_choice == 'onmt':
        onmt_train(args)
    if args.framework_choice == 'custom':
        ...
