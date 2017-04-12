""" Data model for the API retriever. """

import codecs
import csv
import json
import logging
import time
import requests

from random import randint
from jsmin import jsmin
from _socket import gaierror
from requests.packages.urllib3.exceptions import MaxRetryError
from requests.packages.urllib3.exceptions import NewConnectionError
from uritemplate import URITemplate
from util.exceptions import IllegalArgumentError, IllegalConfigurationError

# get root logger
logger = logging.getLogger('api-retriever_logger')


class EntityConfiguration(object):
    """
    An API entity configuration specifies:
        * how to identify an entity
        * how to validate existing information about an entity (optionally)
        * which information should be retrieved about an entity
        * how this information should be extract from the JSON response.
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
            # check if a JSON mapping exists for all validation parameters
            for parameter in config["validation_parameter_names"]:
                if parameter not in config["json_mapping"]:
                    raise IllegalConfigurationError("No JSON mapping for validation parameter " + parameter)

            # list with parameter names identifying the entity
            self.id_parameter_names = config["id_parameter_names"]
            # list with parameter names that should be validated using the API
            self.validation_parameter_names = config["validation_parameter_names"]
            # dictionary with mapping of parameter names to values in the JSON response
            self.json_mapping = config["json_mapping"]
            # URITemplate to retrieve information about an entity (may include API key)
            self.uri_template = URITemplate(config["uri_template"])
            # API key to include in the uri_template
            self.api_key = config["api_key"]
            # configure if duplicate values in the input files should be ignored.
            self.ignore_duplicates = config["ignore_duplicates"]
            # configure the randomized delay interval (ms) between two API requests (trying to prevent getting blocked)
            self.delay_min = config["delay"][0]
            self.delay_max = config["delay"][1]

        except KeyError:
            raise IllegalConfigurationError("Parsing configuration file failed.")


class Entity(object):
    """
    Class representing one API entity for which information should be retrieved over an API.
    """

    def __init__(self, configuration, id_parameter_values, validation_parameter_values):
        """
        To initialize an entity, a corresponding entity configuration together with values for the id parameter(s)
        and (optional) validation parameter(s) are needed.
        :param configuration: an object of class EntityConfiguration
        :param id_parameter_values: values for the id parameters defined in the configuration
        :param validation_parameter_values: values for the validation parameters defined in the configuration
        """

        # check if number of ID parameters matches number of values
        if not len(id_parameter_values) == len(configuration.id_parameter_names):
            raise IllegalArgumentError("Wrong number of ID parameter values: "
                                       + str(len(id_parameter_values)))

        # check if number of validation parameters matches number of values
        if not len(validation_parameter_values) == len(configuration.validation_parameter_names):
            raise IllegalArgumentError("Wrong number of validation parameter values: "
                                       + str(len(validation_parameter_values)))

        # corresponding entity configuration
        self.configuration = configuration
        # parameters needed to identify entity
        self.id_parameters = dict.fromkeys(configuration.id_parameter_names)
        # optional parameters to validate existing entity parameters
        self.validation_parameters = dict.fromkeys(configuration.validation_parameter_names)
        # parameters that should be retrieved using API (must include validation parameters)
        self.api_parameters = dict.fromkeys(configuration.json_mapping.keys())

        # set values for ID parameters
        for parameter_name in configuration.id_parameter_names:
            if parameter_name not in id_parameter_values:
                raise IllegalArgumentError("Illegal ID parameter name: " + parameter_name)
            self.id_parameters[parameter_name] = id_parameter_values[parameter_name]

        # set values for validation parameters
        for parameter_name in configuration.validation_parameter_names:
            if parameter_name not in validation_parameter_values:
                raise IllegalArgumentError("Illegal validation parameter name: " + parameter_name)
            self.validation_parameters[parameter_name] = validation_parameter_values[parameter_name]

    def equals(self, other_entity):
        """
        Function to compare two entities according to their ID parameters (needed to remove duplicates).
        :param other_entity: the entity to compare self to
        :return: True if entities have the same ID parameters, False otherwise
        """

        # compare ID parameters
        for parameter in self.id_parameters.keys():
            try:
                if not self.id_parameters[parameter] == other_entity.id_parameters[parameter]:
                    return False
            except KeyError:
                # parameter does not exist in other entity
                return False
        return True

    def __str__(self):
        return str(self.id_parameters)

    def retrieve_data(self, session):
        """
        Retrieve information about entity using existing session.
        :param session: requests session to use for data retrieval
        :return: 1 if data about entity has been retrieved, 0 otherwise
        """

        try:
            logger.info("Retrieving data for entity: " + str(self))

            # expand URI for this entity
            uri_parameter_mapping = dict.fromkeys(self.configuration.uri_template.variable_names)
            for var in uri_parameter_mapping.keys():
                if var == "api_key":
                    val = self.configuration.api_key
                else:
                    val = self.id_parameters.get(var, None)

                if val:
                    uri_parameter_mapping[var] = val
                else:
                    IllegalArgumentError("Value for URI parameter " + var + " missing.")
            uri = self.configuration.uri_template.expand(uri_parameter_mapping)

            # reduce request frequency as configured
            delay = randint(self.configuration.delay_min, self.configuration.delay_max)  # delay between requests in milliseconds
            time.sleep(delay / 1000)  # sleep for delay ms to not get blocked by Airbnb

            # retrieve data
            data = session.get(uri)

            if not data.ok:
                logger.error("Error " + str(data.status_code) + ": Could not retrieve data for entity " + str(self)
                             + ". Response: " + str(data.content))
                return 0
            else:
                # deserialize JSON string
                data_json = json.loads(data.text)

                # extract data for all parameters according to access path defined in JSON mapping
                for parameter in self.configuration.json_mapping:
                    access_path = self.configuration.json_mapping[parameter]
                    value = data_json  # start with whole JSON object
                    for step in access_path:
                        try:
                            value = data_json[step]
                        except KeyError:
                            logger.debug("Could not retrieve data for parameter " + parameter + " of entity " + str(self))
                            break
                    if value:
                        if parameter in self.validation_parameters:
                            if not value == self.validation_parameters[parameter]:
                                logger.error("Validation failed for parameter " + parameter + " of entity " + str(self))
                        else:
                            self.api_parameters[parameter] = value
                    else:
                        logger.debug("Could not retrieve data for parameter " + parameter + " of entity " + str(self))

                logger.info("Retrieved data for entity: " + str(self))
                return 1
        except (gaierror,
                ConnectionError,
                MaxRetryError,
                NewConnectionError):
            logger.error("An error occurred while getting data for entity  " + str(self))


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
        :param delimiter: column delimiter in CSV (typically ',')
        """

        # read CSV as UTF-8 encoded file (see also http://stackoverflow.com/a/844443)
        with codecs.open(input_file, encoding='utf8') as fp:
            logger.info("Reading entities from " + input_file + "...")
            reader = csv.reader(fp, delimiter=delimiter)
            header = next(reader, None)
            parameter_indices = dict.fromkeys(self.configuration.id_parameter_names
                                              + self.configuration.validation_parameter_names)
            id_parameter_values = dict.fromkeys(self.configuration.id_parameter_names)
            validation_parameter_values = dict.fromkeys(self.configuration.validation_parameter_names)

            if not header:
                raise IllegalArgumentError("Missing header in CSV file.")

            # number of columns must equal number of ID and validation parameters
            if not len(header) == len(parameter_indices):
                raise IllegalArgumentError("Wrong number of columns in CSV file.")

            # check if columns and parameters match, store index
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

                        if parameter in id_parameter_values.keys():  # ID parameter
                            id_parameter_values[parameter] = value
                        elif parameter in validation_parameter_values.keys():  # validation parameter
                            validation_parameter_values[parameter] = value

                    # create entity from values in row
                    new_entity = Entity(self.configuration, id_parameter_values, validation_parameter_values)

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
            count += entity.retrieve_data(self.session)
        logger.info("Data about " + str(count) + " entities has been retrieved.")
