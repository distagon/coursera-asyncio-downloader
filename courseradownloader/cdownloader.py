#!/usr/bin/env python3

import os
import argparse
from courseradownloader import Downloader


def parse_arguments():
    """
    Handle the command line arguments
    """
    parser = argparse.ArgumentParser(
        prog="coursera-dowloader",
        formatter_class=argparse.RawDescriptionHelpFormatter)

    def check_directory(directory):
        if not os.path.isdir(directory):
            raise argparse.ArgumentTypeError(
                'Directory is not exists: %s' % directory)
        return directory

    parser.add_argument(
        "-n",
        "--name",
        required=True,
        action="store",
        dest="name",
        type=str,
        help="Coursera class name")

    parser.add_argument(
        "-u",
        "--username",
        required=True,
        action="store",
        dest="username",
        type=str,
        help="Coursera username")

    parser.add_argument(
        "-p",
        "--password",
        required=True,
        action="store",
        dest="password",
        type=str,
        help="Coursera password")

    parser.add_argument(
        "-c",
        "--chapter",
        required=False,
        default=None,
        action="store",
        dest="chapter",
        type=int,
        help="Coursera class chapters to download."
             " It will download starting with this chapter")

    parser.add_argument(
        "-d",
        "--directory",
        required=False,
        default=os.path.curdir,
        action="store",
        dest="directory",
        type=check_directory,
        help="Directory to save downloaded files")

    parser.add_argument(
        "--concurrency",
        required=False,
        default=10,
        action="store",
        dest="concurrency",
        type=int,
        help="Number of coroutines to download")

    return parser.parse_args()


def main():
    args = parse_arguments()
    downloader = Downloader(
        args.name, args.username, args.password,
        args.concurrency, args.directory, args.chapter)
    downloader.start()


if __name__ == "__main__":
    main()
