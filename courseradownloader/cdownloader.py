#!/usr/bin/env python3

import os
import argparse
import configparser
from courseradownloader import Downloader, logger


DEFAULT_CONFIG_FILENAME = "coursera.conf"
DEFAULT_CONFIGS = [
    os.path.expanduser("~/{}".format(DEFAULT_CONFIG_FILENAME)),
    os.path.join(os.path.curdir, DEFAULT_CONFIG_FILENAME)
]
DESCRIPTION_TEXT = """
    Set mandatory arguments name, username, password either in a config file
    or in the command line. The config file can be set in the command line
    using the argument --config. Also the file coursera.conf will be seek in
    the current directory and in the home directory of the current user.
    In the case of many config files are being found they will be meld in the
    next order (home directory, current directory, command line argument).
    Format of the file:

    classname = some_coursera_class_name
    username = cursera_username
    password = coursera_password
    .....
    optional argumenst, if required
"""


def filter_config_files(*args):
    for filename in args:
        if filename and os.path.isfile(filename):
            yield filename


def read_config(filename):

    def add_section_header(properties_file, header_name):
        yield "[{}]\n".format(header_name)
        for line in properties_file:
            yield line

    try:
        fln = open(filename, encoding="utf-8")
        config = configparser.ConfigParser()
        config.read_file(add_section_header(fln, "asection"), source=filename)
        return dict(config["asection"])
    except configparser.Error as err:
        logger.error(err)
        return {}


def read_configs(*args):
    result = {}
    for filename in args:
        result.update(read_config(filename))
    return result


def check_options(options):
    absent_options = []
    if not options.get("classname"):
        absent_options.append("classname")
    if not options.get("username"):
        absent_options.append("username")
    if not options.get("password"):
        absent_options.append("password")
    if absent_options:
        print(
            "Absent parameters: %s.\nYou should set them either in the"
            " config file or in the command line.\n" %
            ", ".join(absent_options))
        return False
    return True


def prepare_parser():
    """
    Handle the command line arguments
    """
    parser = argparse.ArgumentParser(
        prog="cdownloader",
        description="\n".join(
            [s.lstrip() for s in DESCRIPTION_TEXT.splitlines()]),
        formatter_class=argparse.RawDescriptionHelpFormatter)

    def check_directory(directory):
        if not os.path.isdir(directory):
            raise argparse.ArgumentTypeError(
                'Directory is not exists: %s' % directory)
        return directory

    def check_config(filename):
        if not os.path.isfile(filename):
            raise argparse.ArgumentTypeError(
                'Filename is not exists: %s' % filename)
        return filename

    parser.add_argument(
        "-n",
        "--name",
        required=False,
        action="store",
        dest="name",
        type=str,
        help="Coursera class name")

    parser.add_argument(
        "-u",
        "--username",
        required=False,
        action="store",
        dest="username",
        type=str,
        help="Coursera username")

    parser.add_argument(
        "-p",
        "--password",
        required=False,
        action="store",
        dest="password",
        type=str,
        help="Coursera password")

    parser.add_argument(
        "-c",
        "--chapter",
        required=False,
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
        help="Directory to save downloaded files."
             " Default is current directory")

    parser.add_argument(
        "--config",
        required=False,
        action="store",
        dest="config",
        type=check_config,
        help="Coursera config")

    parser.add_argument(
        "--concurrency",
        required=False,
        default=10,
        action="store",
        dest="concurrency",
        type=int,
        help="Number of coroutines to download. Default is 10")

    return parser


def main():
    parser = prepare_parser()
    options = vars(parser.parse_args())
    allowed_configs = DEFAULT_CONFIGS + [options["config"]]
    config_files = list(filter_config_files(*allowed_configs))
    options.update(read_configs(*config_files))
    options = {k: v for k, v in options.items() if v}
    if not check_options(options):
        parser.print_help()
        return
    Downloader(**options).start()


if __name__ == "__main__":
    main()
