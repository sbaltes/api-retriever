import argparse
import logging

from retriever.entity import EntityConfiguration, EntityList

# get global logger
logger = logging.getLogger('airbnb_logger')


def get_argument_parser():
    arg_parser = argparse.ArgumentParser(
        description='Retrieve data about entities using an API,'
    )
    arg_parser.add_argument(
        '-c', '--config-file',
        required=True,
        help='JSON file with entity configuration.',
        dest='config_file'
    )
    arg_parser.add_argument(
        '-i', '--input-file',
        required=True,
        help='CSV file with parameters for identifying entities and for validation.',
        dest='input_file'
    )
    arg_parser.add_argument(
        '-o', '--output-dir',
        required=True,
        help='Path to output directory for retrieved data',
        dest='output_dir'
    )
    arg_parser.add_argument(
        '-d', '--delimiter',
        required=False,
        default=',',
        help='delimiter in csv file (default: \',\')',
        dest='delimiter'
    )
    return arg_parser


def main():
    # parse command line arguments
    parser = get_argument_parser()
    args = parser.parse_args()

    # parse configuration and create entity list
    config = EntityConfiguration(args.config_file)
    entities = EntityList(config)

    # read entities from CSV
    entities.read_from_csv(args.input_file, args.delimiter)

    # retrieve data using API
    entities.retrieve_data()


if __name__ == '__main__':
    main()
