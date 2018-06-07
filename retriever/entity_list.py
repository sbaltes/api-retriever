import codecs
import csv
import json
import logging
import os
import requests

from _socket import gaierror
from collections import OrderedDict
from orderedset import OrderedSet
from urllib3.exceptions import MaxRetryError, NewConnectionError

from retriever.entity import Entity
from retriever.entity_configuration import EntityConfiguration
from util.exceptions import IllegalArgumentError, IllegalConfigurationError

# get root logger
logger = logging.getLogger('api-retriever_logger')


class EntityList(object):
    """ List of API entities. """

    def __init__(self, configuration, start_index=0, chunk_size=0):
        """
        To initialize the list, an entity configuration is needed.
        :param configuration: Object of class EntityConfiguration.
        """

        assert start_index >= 0
        assert chunk_size >= 0

        self.configuration = configuration
        # list that stores entity objects
        self.entities = []
        # session for data retrieval
        self.session = requests.Session()
        # index of first element to import from input_file (default: 0)
        self.start_index = start_index
        # number of elements to import from input_file (default: 0, meaning max.)
        self.chunk_size = chunk_size

    def add(self, entities):
        error_message = "Argument must be object of class Entity or class EntityList."

        if isinstance(entities, Entity):
            self.entities.append(entities)
        elif isinstance(entities, EntityList):
            self.entities = self.entities + entities.entities
        elif isinstance(entities, list):
            for element in entities:
                if not isinstance(element, Entity):
                    raise IllegalArgumentError(error_message)
                self.entities.append(element)
        else:
            raise IllegalArgumentError(error_message)
        self.set_predecessors()

    def set_predecessors(self):
        for pos in range(1, len(self.entities)):
            self.entities[pos].predecessor = self.entities[pos-1]

    def read_from_csv(self, input_file, delimiter):
        """
        Read entity input parameter values from a CSV file (header required).
        :param input_file: Path to the CSV file.
        :param delimiter: Column delimiter in CSV file (typically ',').
        """

        # read CSV as UTF-8 encoded file (see also http://stackoverflow.com/a/844443)
        with codecs.open(input_file, encoding='utf8') as fp:
            if self.chunk_size == 0:
                interval = "[" + str(self.start_index) + ", max]"
            else:
                interval = "[" + str(self.start_index) + ", " + str(self.start_index+self.chunk_size-1) + "]"
            logger.info("Reading entities in " + interval + " from " + input_file + "...")

            reader = csv.reader(fp, delimiter=delimiter)

            # check if one of the input parameters is an URI
            uri_input_parameters = OrderedDict()
            for parameter in self.configuration.input_parameters:
                if isinstance(parameter, list):
                    if not len(parameter) == 3 and parameter[1].startswith("http"):
                        raise IllegalConfigurationError("Malformed URI input parameter, should be" +
                                                        "[parameter, uri, response_filter].")

                    uri_parameter = parameter[0]
                    uri = parameter[1]
                    response_filter = parameter[2]
                    logger.info("Found URI input parameter: " + str(uri_parameter))

                    logger.info("Retrieving data for URI input parameter " + str(uri_parameter) + "...")

                    try:
                        # retrieve data
                        response = self.session.get(uri)

                        if response.ok:
                            logger.info("Successfully retrieved data for URI input parameter " + str(uri_parameter) + ".")

                            # deserialize JSON string
                            json_response = json.loads(response.text)

                            filter_result = Entity.apply_filter(json_response, response_filter)
                            uri_input_parameters[uri_parameter] = filter_result

                        else:
                            raise IllegalConfigurationError("Error " + str(response.status_code)
                                                            + ": Could not retrieve data for URI input parameter "
                                                            + str(uri_parameter) + ". Response: "
                                                            + str(response.content))

                    except (gaierror,
                            ConnectionError,
                            MaxRetryError,
                            NewConnectionError):
                        logger.error("An error occurred while retrieving data for URI input parameter "
                                     + str(uri_parameter) + ".")

                    # replace URI parameter with URI parameter name
                    self.configuration.input_parameters.remove(parameter)
                    self.configuration.input_parameters.append(uri_parameter)

            # dictionary to store CSV column indices for input parameters
            input_parameter_indices = OrderedDict.fromkeys(self.configuration.input_parameters)

            # read header
            header = next(reader, None)
            if not header:
                raise IllegalArgumentError("Missing header in CSV file.")

            # number of columns must equal number of input parameters minus number of uri input parameters
            if not len(header) == len(input_parameter_indices) - len(uri_input_parameters):
                raise IllegalArgumentError("Wrong number of columns in CSV file.")

            # check if columns and parameters match, store indices
            for index in range(len(header)):
                if header[index] in input_parameter_indices.keys():
                    input_parameter_indices[header[index]] = index
                else:
                    raise IllegalArgumentError("Unknown column name in CSV file: " + header[index])

            # read CSV file
            predecessor = None
            current_index = 0
            for row in reader:
                # only read value from start_index to start_index+chunk_size-1 (if chunk_size is 0, read until the end)
                if current_index < self.start_index:
                    current_index += 1
                    continue
                elif (self.chunk_size != 0) and (current_index >= self.start_index+self.chunk_size):
                    current_index += 1
                    break

                if row:
                    # dictionary to store imported parameter values
                    input_parameter_values = OrderedDict.fromkeys(self.configuration.input_parameters)

                    # read parameters
                    for parameter in input_parameter_values.keys():
                        # if parameter was URI input parameter, get value from dict
                        if parameter in uri_input_parameters.keys():
                            value = uri_input_parameters[parameter]
                        else:  # get value from CSV
                            parameter_index = input_parameter_indices[parameter]
                            value = row[parameter_index]
                        if value:
                            input_parameter_values[parameter] = value
                        else:
                            raise IllegalArgumentError("No value for parameter " + parameter)

                    # create entity from values in row
                    new_entity = Entity(self.configuration, input_parameter_values, predecessor)
                    predecessor = new_entity

                    # if ignore_input_duplicates is configured, check if entity already exists
                    if self.configuration.ignore_input_duplicates:
                        entity_exists = False
                        for entity in self.entities:
                            if entity.equals(new_entity):
                                entity_exists = True
                        if not entity_exists:
                            # add new entity to list
                            self.entities.append(new_entity)
                    else:  # ignore_input_duplicates is false
                        # add new entity to list
                        self.entities.append(new_entity)
                else:
                    raise IllegalArgumentError("Wrong CSV format.")

                current_index += 1

        logger.info(str(len(self.entities)) + " entities have been imported.")

    def resolve_range_vars(self):
        """
        Create entities within range if range var is configured
        """
        if len(self.configuration.range_vars) > 0:
            new_entities = list()
            for range_var_name in self.configuration.range_vars.keys():
                range_var = self.configuration.range_vars.get(range_var_name)
                for entity in self.entities:
                    for i in range(range_var.start, range_var.stop, range_var.step):
                        new_entity = Entity(entity.configuration, {
                                **entity.input_parameters,
                                range_var_name: str(i)
                            }, None)
                        new_entity.root_entity = entity
                        new_entities.append(new_entity)
                self.entities = new_entities
                new_entities = list()
        self.set_predecessors()

    def retrieve_data(self):
        """
        Retrieve data for all entities in the list.
        """
        # retrieve data and filter list according to the return value of entity.retrieve_data
        # (may be false, e.g., because of filter callback)

        self.resolve_range_vars()

        if self.configuration.post_request_callback_filter:
            self.entities = [entity for entity in self.entities if entity.retrieve_data(self.session)]
        else:
            for entity in self.entities:
                entity.retrieve_data(self.session)

        logger.info("Data for " + str(len(self.entities)) + " entities has been saved.")

    def execute_chained_request(self, config_dir):
        """
        Execute the chained request for all entities in the list.
        :param config_dir: Path to directory with entity configurations as JSON files.
        :return: The entities retrieved by the chained requests.
        """

        # derive path to JSON file with configuration for chained request
        config_file_path = os.path.join(
            config_dir,
            '{0}.json'.format(self.configuration.chained_request_name)
        )

        logger.info("Reading entity configuration for chained request:")
        chained_request_config = EntityConfiguration.create_from_json(config_file_path)

        if chained_request_config.name == self.configuration.chained_request_name:
            logger.info("Executing chained requests...")

            chained_request_entities = EntityList(chained_request_config)
            for entity in self.entities:
                # get chained request entities
                chained_request_entities.add(entity.get_chained_request_entities(chained_request_config))
                # set predecessors
                chained_request_entities.set_predecessors()
                # retrieve data for chained entities
                chained_request_entities.retrieve_data()

            return chained_request_entities

        raise IllegalConfigurationError("Configuration name <" + str(chained_request_config.name)
                                        + "> is not identical to chained request name <"
                                        + str(self.configuration.chained_request_name) + ">.")

    def write_to_csv(self, output_dir, delimiter):
        """
        Export entities together with retrieved data to a CSV file.
        :param output_dir: Target directory for generated CSV file.
        :param delimiter: Column delimiter in CSV file (typically ',').
        """

        if len(self.entities) == 0:
            logger.info("Nothing to export.")
            return

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        if self.chunk_size != 0:
            filename = '{0}_{1}-{2}.csv'.format(self.configuration.name, str(self.start_index),
                                                str(self.start_index + min(len(self.entities), self.chunk_size) - 1))
        else:
            filename = '{0}.csv'.format(self.configuration.name)

        file_path = os.path.join(output_dir, filename)

        # write entity list to UTF8-encoded CSV file (see also http://stackoverflow.com/a/844443)
        with codecs.open(file_path, 'w', encoding='utf8') as fp:
            logger.info('Exporting entities to ' + file_path + '...')
            writer = csv.writer(fp, delimiter=delimiter)

            # check if input and output parameters overlap -> validate these parameters later
            validation_parameters = OrderedSet(self.configuration.input_parameters).intersection(
                OrderedSet(self.configuration.output_parameter_mapping.keys())
            )

            # get column names for CSV file (start with input parameters)
            column_names = self.configuration.input_parameters + [
                parameter for parameter in self.configuration.output_parameter_mapping.keys()
                if parameter not in validation_parameters
            ]

            # check if an output parameter has been added and/or removed by a callback function and update column names
            parameters_removed = OrderedSet()
            parameters_added = OrderedSet()
            for entity in self.entities:
                parameters_removed.update(OrderedSet(self.configuration.output_parameter_mapping.keys()).difference(
                    OrderedSet(entity.output_parameters.keys()))
                )
                parameters_added.update(OrderedSet(entity.output_parameters.keys()).difference(
                    OrderedSet(self.configuration.output_parameter_mapping.keys()))
                )
            for parameter in parameters_removed:
                column_names.remove(parameter)
            for parameter in parameters_added:
                column_names.append(parameter)

            # write header of CSV file
            writer.writerow(column_names)

            for entity in self.entities:
                try:
                    row = OrderedDict.fromkeys(column_names)

                    # check validation parameters
                    for parameter in validation_parameters:
                        if entity.output_parameters[parameter]:
                            if str(entity.input_parameters[parameter]) == str(entity.output_parameters[parameter]):
                                logger.info("Validation of parameter " + parameter + " successful for entity "
                                            + str(entity) + ".")
                            else:
                                logger.error("Validation of parameter " + parameter + " failed for entity "
                                             + str(entity)
                                             + ": Expected: " + str(entity.input_parameters[parameter])
                                             + ", Actual: " + str(entity.output_parameters[parameter])
                                             + ". Retrieved value will be exported.")
                        else:
                            logger.error("Validation of parameter " + parameter + " failed for entity " + str(entity)
                                         + ": Empty value.")

                    # write data
                    for column_name in column_names:
                        if column_name in entity.output_parameters.keys():
                            row[column_name] = entity.output_parameters[column_name]
                        elif column_name in entity.input_parameters.keys():
                            row[column_name] = entity.input_parameters[column_name]

                    if len(row) == len(column_names):
                        writer.writerow(list(row.values()))
                    else:
                        raise IllegalArgumentError(str(len(column_names) - len(row)) + " parameter(s) is/are missing "
                                                                                       "for entity " + str(entity))

                except UnicodeEncodeError:
                    logger.error("Encoding error while writing data for entity: " + str(entity))

            logger.info(str(len(self.entities)) + ' entities have been exported.')

    def save_raw_files(self, output_dir):
        """
        Export raw content from entities to files.
        :param output_dir: Target directory for exported files.
        """

        if len(self.entities) == 0:
            logger.info("Nothing to export.")
            return

        output_dir = os.path.join(output_dir, self.configuration.name)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        logger.info('Exporting raw content of entities to directory ' + str(output_dir) + '...')
        for entity in self.entities:
            if not entity.configuration.raw_download:
                raise IllegalConfigurationError("Raw download not configured for entity " + str(entity))

            if entity.output_parameters[entity.configuration.raw_parameter] is not None:
                if "destination" not in entity.output_parameters.keys() or not entity.output_parameters["destination"]:
                    raise IllegalConfigurationError("Destination path not configured for entity " + str(entity))

                # join output path, create missing directories
                dest_file = os.path.join(output_dir, entity.output_parameters["destination"])
                dest_dir = os.path.dirname(dest_file)
                if not os.path.exists(dest_dir):
                    os.makedirs(dest_dir)

                logger.info("Writing " + str(dest_file) + "...")
                # see http://stackoverflow.com/a/13137873
                with open(dest_file, 'wb') as f:
                    f.write(entity.output_parameters[entity.configuration.raw_parameter])

                # add downloaded flag to output
                entity.output_parameters["downloaded"] = True
            else:
                # add downloaded flag to output
                entity.output_parameters["downloaded"] = False

            # remove raw content parameter from output
            entity.output_parameters.pop(entity.configuration.raw_parameter)

        logger.info("Raw content of " + str(len(self.entities)) + ' entities has been exported.')

    def flatten_output(self):
        """
        Flattens the entries of output parameters that is a list of dicts,
        i.e. converts them to separate columns.
        """
        logger.info("Flattening output...")

        # search for list parameter
        list_parameter_name = None
        other_parameters = list()
        for entity in self.entities:
            for parameter_name in entity.output_parameters.keys():
                parameter = entity.output_parameters.get(parameter_name)
                # only process one output parameter
                if list_parameter_name is None and isinstance(parameter, list):
                    list_parameter_name = parameter_name
                else:
                    other_parameters.append(parameter_name)
            if list_parameter_name is not None:
                break

        if list_parameter_name is None:
            logger.info("No list parameter found.")
            return

        logger.info("Flattening output for parameter \"" + list_parameter_name + "\"...")

        flattened_entities = list()
        for entity in self.entities:
            list_parameter = entity.output_parameters.get(list_parameter_name)
            # remove output parameter to be flattened
            entity.output_parameters.pop(list_parameter_name)

            # skip if retrieval failed
            if list_parameter is None:
                continue

            for element in list_parameter:
                if not isinstance(element, dict):
                    logger.info("List elements must be dicts, aborting...")
                    return

                flattened_entity = Entity(entity.configuration, entity.input_parameters, entity.predecessor)
                # add old and new output parameters
                flattened_entity.output_parameters = {
                    **entity.output_parameters,
                    **element
                }
                flattened_entities.append(flattened_entity)

        # replace entities with flattened ones
        self.entities = flattened_entities
