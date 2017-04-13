""" Data model for the API retriever. """

import codecs
import csv
import json
import logging
import os
import time
import requests

from random import randint
from jsmin import jsmin
from _socket import gaierror
from requests.packages.urllib3.exceptions import MaxRetryError
from requests.packages.urllib3.exceptions import NewConnectionError
from retriever import callbacks
from util.exceptions import IllegalArgumentError, IllegalConfigurationError
from util.uri_template import URITemplate


# get root logger
logger = logging.getLogger('api-retriever_logger')


class EntityConfiguration(object):
    """
    An API entity configuration specifies:
        * the input parameters for an entity
        * if and how existing information about an entity should be validated (-> validation parameters)
        * which information should be retrieved about an entity (-> output parameters)
        * how this information should be extract from the API response (-> response callback).
    """

    def __init__(self, json_config_file):
        """
        Create API entity configuration from a JSON file.
        :param json_config_file: path to the JSON file with the configuration
        """

        # read config file
        with open(json_config_file) as config_file:
            # remove comments from JSON file (which we allow, but the standard does not)
            stripped_json = jsmin(config_file.read())
            # parse JSON file
            config = json.loads(stripped_json)

        # initialize configuration
        try:
            # name of configured entities
            self.name = config["name"]
            # list with parameters that identify the entity (correspond to columns in the input CSV)
            self.input_parameters = config["input_parameters"]
            # list with parameters that are validated against the API (correspond to columns in the input CSV)
            self.validation_parameters = config["validation_parameters"]
            # dictionary with mapping of parameter names to values in the response
            self.output_parameter_mapping = config["output_parameter_mapping"]
            # uri templates to retrieve information about the entity (may include API key)
            self.uri_template = URITemplate(config["uri_template"])
            # load callback to extract output parameters from a JSON API response
            try:
                self.response_callback = getattr(callbacks, config["response_callback"])
            except AttributeError:
                raise IllegalConfigurationError("Parsing configuration file failed: Callback "
                                                + config["response_callback"] + " not found.")
            # API key to include in the uri_template
            self.api_key = config["api_key"]
            # configure if duplicate values in the input files should be ignored.
            self.ignore_duplicates = config["ignore_duplicates"]
            # configure the randomized delay interval (ms) between two API requests (trying to prevent getting blocked)
            self.delay_min = config["delay"][0]
            self.delay_max = config["delay"][1]

        except KeyError as e:
            raise IllegalConfigurationError("Parsing configuration file failed: Parameter " + str(e) + " not found.")


class Entity(object):
    """
    Class representing one API entity for which information should be retrieved over an API.
    """

    def __init__(self, configuration, input_parameter_values, validation_parameter_values):
        """
        To initialize an entity, a corresponding entity configuration together with values for the input parameter(s)
        and (optional) validation parameter(s) are needed.
        :param configuration: an object of class EntityConfiguration
        :param input_parameter_values: values for the input parameters defined in the configuration
        :param validation_parameter_values: values for the validation parameters defined in the configuration
        """

        # check if number of input parameters matches number of values
        if not len(input_parameter_values) == len(configuration.input_parameters):
            raise IllegalArgumentError("Wrong number of input parameter values: "
                                       + str(len(input_parameter_values)))

        # check if number of validation parameters matches number of values
        if not len(validation_parameter_values) == len(configuration.validation_parameters):
            raise IllegalArgumentError("Wrong number of validation parameter values: "
                                       + str(len(validation_parameter_values)))

        # corresponding entity configuration
        self.configuration = configuration
        # parameters needed to identify entity read from CSV
        self.input_parameters = dict.fromkeys(configuration.input_parameters)
        # optional parameters to validate existing entity parameters
        self.validation_parameters = dict.fromkeys(configuration.validation_parameters)
        # parameters that should be retrieved using the API
        self.output_parameters = dict.fromkeys(configuration.output_parameter_mapping.keys())

        # set values for input parameters
        for parameter in configuration.input_parameters:
            if parameter not in input_parameter_values:
                raise IllegalArgumentError("Illegal input parameter: " + parameter)
            self.input_parameters[parameter] = input_parameter_values[parameter]

        # set values for validation parameters
        for parameter in configuration.validation_parameters:
            if parameter not in validation_parameter_values:
                raise IllegalArgumentError("Illegal validation parameter: " + parameter)
            self.validation_parameters[parameter] = validation_parameter_values[parameter]

        # get uri for this entity from uri template in configuration
        uri_variable_values = self.input_parameters
        uri_variable_values["api_key"] = self.configuration.api_key
        self.uri = self.configuration.uri_template.replace_variables(uri_variable_values)

    def equals(self, other_entity):
        """
        Function to compare two entities according to their input parameters (needed to remove duplicates).
        :param other_entity: the entity to compare self to
        :return: True if entities have the same input parameters, False otherwise
        """

        # compare input parameters
        for parameter in self.input_parameters.keys():
            try:
                if not self.input_parameters[parameter] == other_entity.input_parameters[parameter]:
                    return False
            except KeyError:
                # parameter does not exist in other entity
                return False
        return True

    def __str__(self):
        return str(self.input_parameters)

    def retrieve_data(self, session):
        """
        Retrieve information about entity using an existing session.
        :param session: requests session to use for data retrieval
        :return: True if data about entity has been retrieved, False otherwise
        """

        try:
            logger.info("Retrieving data for entity " + str(self) + "...")

            # reduce request frequency as configured
            delay = randint(self.configuration.delay_min,
                            self.configuration.delay_max)  # delay between requests in milliseconds
            time.sleep(delay / 1000)  # sleep for delay ms to not get blocked by Airbnb

            # retrieve data
            response = session.get(self.uri)

            if not response.ok:
                logger.error("Error " + str(response.status_code) + ": Could not retrieve data for entity " + str(self)
                             + ". Response: " + str(response.content))
                return False
            else:
                logger.info("Successfully retrieved data for entity " + str(self) + ".")
                # deserialize JSON string
                json_response = json.loads(response.text)
                self.configuration.response_callback(self, json_response)
                return True
        except (gaierror,
                ConnectionError,
                MaxRetryError,
                NewConnectionError):
            logger.error("An error occurred while retrieving data for entity  " + str(self))


class EntityList(object):
    """ List of API entities. """

    def __init__(self, configuration):
        """
        To initialize the list, an entity configuration is needed.
        :param configuration: object of class EntityConfiguration
        """
        self.configuration = configuration
        # list to stores entity objects
        self.list = []
        # session for data retrieval
        self.session = requests.Session()

    def read_from_csv(self, input_file, delimiter):
        """
        Read entity ID and (optionally) validation parameters from a CSV file (header required).
        :param input_file: path to the CSV file
        :param delimiter: column delimiter in CSV file (typically ',')
        """

        # read CSV as UTF-8 encoded file (see also http://stackoverflow.com/a/844443)
        with codecs.open(input_file, encoding='utf8') as fp:
            logger.info("Reading entities from " + input_file + "...")
            reader = csv.reader(fp, delimiter=delimiter)
            header = next(reader, None)
            # save column indices for input and validation parameters
            parameter_indices = dict.fromkeys(self.configuration.input_parameters
                                              + self.configuration.validation_parameters)
            input_parameter_values = dict.fromkeys(self.configuration.input_parameters)
            validation_parameter_values = dict.fromkeys(self.configuration.validation_parameters)

            if not header:
                raise IllegalArgumentError("Missing header in CSV file.")

            # number of columns must equal number of input and validation parameters
            if not len(header) == len(parameter_indices):
                raise IllegalArgumentError("Wrong number of columns in CSV file.")

            # check if columns and parameters match, store indices
            for index in range(len(header)):
                if not header[index] in parameter_indices.keys():
                    raise IllegalArgumentError("Unknown column name in CSV file: " + header[index])
                parameter_indices[header[index]] = index

            # read CSV file
            for row in reader:
                if row:
                    # read parameters
                    for parameter in parameter_indices.keys():
                        value = row[parameter_indices[parameter]]
                        if not value:
                            raise IllegalArgumentError("No value for parameter " + parameter)

                        if parameter in input_parameter_values.keys():  # input parameter
                            input_parameter_values[parameter] = value
                        elif parameter in validation_parameter_values.keys():  # validation parameter
                            validation_parameter_values[parameter] = value

                    # create entity from values in row
                    new_entity = Entity(self.configuration, input_parameter_values, validation_parameter_values)

                    # check if entity already exists (if ignore_duplicates is configured)
                    if self.configuration.ignore_duplicates:
                        entity_exists = False
                        for entity in self.list:
                            if new_entity.equals(entity):
                                entity_exists = True
                        if not entity_exists:
                            # add new entity to list
                            self.list.append(new_entity)
                    else:
                        # add new entity to list
                        self.list.append(new_entity)
                else:
                    raise IllegalArgumentError("Wrong CSV format.")

        logger.info(str(len(self.list)) + " entities have been imported.")

    def retrieve_data(self):
        """
        Retrieve data for all entities in the list.
        """
        count = 0
        for entity in self.list:
            if entity.retrieve_data(self.session):
                count += 1
        logger.info("Data for " + str(count) + " entities has been retrieved.")

    def write_to_csv(self, output_dir, delimiter):
        """
        Write entities together with retrieved data to a CSV file.
        :param output_dir: target directory for generated CSV file 
        :param delimiter: column delimiter in CSV file (typically ',')
        """

        if len(self.list) == 0:
            logger.info("Nothing to write...")

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        file_path = os.path.join(
            output_dir,
            '{0}.csv'.format(self.configuration.name)
        )

        # write entity list to UTF8-encoded CSV file (see also http://stackoverflow.com/a/844443)
        with codecs.open(file_path, 'w', encoding='utf8') as fp:
            logger.info('Writing entities to ' + file_path + '...')
            writer = csv.writer(fp, delimiter=delimiter)

            # write header of CSV file
            column_names = self.configuration.input_parameters + self.configuration.validation_parameters \
                + list(self.configuration.output_parameter_mapping.keys())
            writer.writerow(column_names)

            for entity in self.list:
                try:
                    row = []
                    for column_name in column_names:
                        if column_name in entity.input_parameters.keys():
                            row.append(entity.input_parameters[column_name])
                        elif column_name in entity.validation_parameters.keys():
                            row.append(entity.validation_parameters[column_name])
                        elif column_name in entity.output_parameters.keys():
                            row.append(entity.output_parameters[column_name])
                    if len(row) == len(column_names):
                        writer.writerow(row)
                    else:
                        raise IllegalArgumentError(str(len(row) - len(column_names)) + " parameters are missing for"
                                                                                       "entity " + str(entity))

                except UnicodeEncodeError:
                    logger.error("Encoding error while writing data for entity: " + str(entity))

            logger.info(str(len(self.list)) + ' entities have been exported.')
