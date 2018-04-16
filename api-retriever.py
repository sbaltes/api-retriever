import argparse
import logging

from retriever.entity import EntityConfiguration, EntityList

# get global logger
logger = logging.getLogger('airbnb_logger')


def get_argument_parser():
    arg_parser = argparse.ArgumentParser(
        description='Retrieve data about entities using a public API,'
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
        '-c', '--config-file',
        required=True,
        help='JSON file with entity configuration.',
        dest='config_file'
    )
    arg_parser.add_argument(
        '-cd', '--config-dir',
        required=False,
        default='config',
        help='Directory with other entity configurations.',
        dest='config_dir'
    )
    arg_parser.add_argument(
        '-d', '--delimiter',
        required=False,
        default=',',
        help='delimiter in csv files (default: \',\')',
        dest='delimiter'
    )
    arg_parser.add_argument(
        '-si', '--start-index',
        type=int,
        required=False,
        default=0,
        help='start index in input list (default: 0)',
        dest='start_index'
    )
    arg_parser.add_argument(
        '-cs', '--chunk-size',
        type=int,
        required=False,
        default=0,
        help='chunk size for this call (default: 0, meaning max.)',
        dest='chunk_size'
    )
    return arg_parser


def main():
    # parse command line arguments
    parser = get_argument_parser()
    args = parser.parse_args()

    # parse configuration and create entity list
    config = EntityConfiguration.create_from_json(args.config_file)
    entities = EntityList(config, args.start_index, args.chunk_size)

    # read entities from CSV
    entities.read_from_csv(args.input_file, args.delimiter)

    # retrieve data using API
    entities.retrieve_data()

    # flatten output (if configured)
    if config.flatten_output:
        entities.flatten_output()

    if config.chained_request_name:
        # execute chained request (if configured)
        chained_entities = entities.execute_chained_request(args.config_dir)
        # write chained entities to CSV file
        chained_entities.write_to_csv(args.output_dir, args.delimiter)
    else:
        if config.raw_download:
            # write raw content to output files
            entities.save_raw_files(args.output_dir)

        # write entities to CSV file
        entities.write_to_csv(args.output_dir, args.delimiter)

if __name__ == '__main__':
    main()
