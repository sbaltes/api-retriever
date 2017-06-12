""" Data model for the API retriever. """

import codecs
import csv
import json
import logging
import os
import time
import requests

from inspect import signature
from random import randint
from jsmin import jsmin
from _socket import gaierror
from requests.packages.urllib3.exceptions import MaxRetryError
from requests.packages.urllib3.exceptions import NewConnectionError
from collections import OrderedDict
from orderedset import OrderedSet

from retriever import callbacks
from util.exceptions import IllegalArgumentError, IllegalConfigurationError
from util.regex import FLATTEN_OPERATOR_REGEX
from util.uri_template import URITemplate

# get root logger
logger = logging.getLogger('api-retriever_logger')


class EntityConfiguration(object):
    """
    An API entity configuration specifies:
        * the input parameters for an entity
        * which information should be retrieved about an entity (-> output parameters)
        * how this information should be retrieved (uri template and api key)
        * the pre- and post-processing that should be done (callbacks)
        * optionally a chained request
    """

    def __init__(self, config_dict):
        """
        Initialize an API entity configuration.
        :param config_dict: A dictionary with all configuration parameters.
        """

        try:
            # name of configured entity
            self.name = config_dict["name"]
            # list with parameters that identify the entity or that should be validated
            # (correspond to columns in the input CSV)
            self.input_parameters = config_dict["input_parameters"]
            # uri templates to retrieve information about the entity (may include API key)
            self.uri_template = URITemplate(config_dict["uri_template"])
            # API key to include in the uri_template
            self.api_key = config_dict["api_key"]
            # check if api key configured when required for uri_template
            uri_vars = self.uri_template.get_variables()
            for var in uri_vars:
                if var == "api_key" and not self.api_key:
                    raise IllegalConfigurationError("API key required for URI template, but not configured.")
            # configure if duplicate values in the input files should be ignored.
            self.ignore_input_duplicates = config_dict["ignore_input_duplicates"]
            # configure the randomized delay interval (ms) between two API requests (trying to prevent getting blocked)
            self.delay_min = config_dict["delay"][0]
            self.delay_max = config_dict["delay"][1]
            # dictionary with mapping of parameter names to values in the response
            self.output_parameter_mapping = config_dict["output_parameter_mapping"]
            # check if raw download is configured
            self.raw_download = False
            self.raw_parameter = None
            for parameter in self.output_parameter_mapping.keys():
                if len(self.output_parameter_mapping[parameter]) == 1\
                        and self.output_parameter_mapping[parameter][0] == "<raw_response>":
                    self.raw_download = True
                    self.raw_parameter = parameter
            # load pre_request_callbacks to validate and/or process the parameters before the request to the API is made
            self.pre_request_callbacks = []
            for callback_name in config_dict["pre_request_callbacks"]:
                self.pre_request_callbacks.append(EntityConfiguration._load_callback(callback_name))
            # configure if filters should be applied when retrieving data
            self.apply_output_filter = config_dict["apply_output_filter"]
            # load post_request_callbacks to process, validate and/or filter output parameters from a JSON API response
            self.post_request_callbacks = []
            for callback_name in config_dict["post_request_callbacks"]:
                self.post_request_callbacks.append(EntityConfiguration._load_callback(callback_name))
            # save (optional) chained request
            self.chained_request_name = None
            self.chained_request_input_parameter_mapping = None
            chained_request = config_dict["chained_request"]
            if len(chained_request) > 0:
                # get name and input parameter mapping for chained request
                self.chained_request_name = chained_request["name"]
                self.chained_request_input_parameters = chained_request["input_parameters"]

        except KeyError as e:
            raise IllegalConfigurationError("Reading configuration failed: Parameter " + str(e) + " not found.")

    @staticmethod
    def _load_callback(callback_name):
        """
        Load a callback function by name and check its form (must have one parameter named "entity").
        :param callback_name: Name of the callback function to load.
        :return: The callback function.
        """
        try:
            callback_function = getattr(callbacks, callback_name)
            callback_parameters = signature(callback_function).parameters
            # check if callback has the correct form (only one parameter named "entity")
            if len(callback_parameters) == 1 and "entity" in callback_parameters:
                return callback_function
            else:
                raise IllegalArgumentError("Invalid callback: " + str(callback_name))
        except AttributeError:
            raise IllegalConfigurationError("Parsing configuration file failed: Callback "
                                            + callback_name + " not found.")

    def equals(self, other_config):
        """
        Compare equality of two entity configurations.
        :param other_config: The entity configuration to compare self to.
        :return: True if the configurations are identical, False otherwise.
        """
        if not self.name == other_config.name:
            return False
        if not self.uri_template.equals(other_config.uri_template):
            return False
        if not self.api_key == other_config.api_key:
            return False
        if not self.ignore_input_duplicates == other_config.ignore_input_duplicates:
            return False
        if not self.delay_min == other_config.delay_min:
            return False
        if not self.delay_max == other_config.delay_max:
            return False

        for parameter in self.input_parameters:
            if parameter not in other_config.input_parameters:
                return False

        for parameter in self.output_parameter_mapping.keys():
            if parameter not in other_config.output_parameter_mapping.keys():
                return False
            if not self.output_parameter_mapping[parameter] == other_config.output_parameter_mapping[parameter]:
                return False

        for callback in self.pre_request_callbacks:
            if callback not in other_config.pre_request_callbacks:
                return False

        if not self.apply_output_filter == other_config.apply_output_filter:
            return False

        for callback in self.post_request_callbacks:
            if callback not in other_config.post_request_callbacks:
                return False

        if self.chained_request_name:
            if not self.chained_request_name == self.chained_request_name:
                return False

            if not other_config.chained_request_input_parameter_mapping:
                return False

            for parameter in self.chained_request_input_parameter_mapping.keys():
                if parameter not in other_config.chained_request_input_parameter_mapping.keys():
                    return False
                if not self.chained_request_input_parameter_mapping[parameter] \
                        == other_config.chained_request_input_parameter_mapping[parameter]:
                    return False

        return True

    @classmethod
    def create_from_json(cls, json_config_file):
        """
        Create API entity configuration from a JSON file.
        :param json_config_file: Path to the JSON file with the configuration.
        """

        logger.info("Reading entity configuration from JSON file...")

        # read config file
        with open(json_config_file) as config_file:
            # remove comments from JSON file (which we allow, but the standard does not)
            stripped_json = jsmin(config_file.read())
            # parse JSON file
            config_dict = json.loads(stripped_json)

        entity_config = EntityConfiguration(config_dict)
        logger.info("Entity configuration successfully imported: " + str(entity_config.name))

        return entity_config


class Entity(object):
    """
    Class representing one API entity for which information should be retrieved over an API.
    """

    def __init__(self, configuration, input_parameter_values):
        """
        To initialize an entity, a corresponding entity configuration together
        and values for the input parameter(s) are needed.
        :param configuration: an object of class EntityConfiguration
        :param input_parameter_values: A dictionary with values for the input parameters defined in the configuration.
        """

        # corresponding entity configuration
        self.configuration = configuration
        # parameters needed to identify entity (or for validation)
        self.input_parameters = OrderedDict.fromkeys(configuration.input_parameters)
        # parameters that should be retrieved using the API
        self.output_parameters = OrderedDict.fromkeys(configuration.output_parameter_mapping.keys())

        # set values for input parameters
        for parameter in configuration.input_parameters:
            if parameter in input_parameter_values:
                self.input_parameters[parameter] = input_parameter_values[parameter]
            else:
                raise IllegalArgumentError("Illegal input parameter: " + parameter)

        # get uri for this entity from uri template in the configuration
        uri_variable_values = {
            **self.input_parameters,
            "api_key": self.configuration.api_key
        }
        self.uri = self.configuration.uri_template.replace_variables(uri_variable_values)

    def equals(self, other_entity):
        """
        Function to compare two entities according to their input parameters (needed to remove duplicates).
        :param other_entity: The entity to compare self to.
        :return: True if entities have the same input parameters, False otherwise.
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
        return str(dict(self.input_parameters))  # cast OrderedDict to dict for a more compact string representation

    def retrieve_data(self, session):
        """
        Retrieve information about entity using an existing session.
        :param session: Requests session to use for data retrieval.
        :return: True if data about entity has been successfully retrieved and no filter callback excluded this entity,
            False otherwise.
        """

        try:
            logger.info("Retrieving data for entity " + str(self) + "...")

            # execute pre_request_callbacks
            for callback in self.configuration.pre_request_callbacks:
                callback(self)

            # reduce request frequency as configured
            delay = randint(self.configuration.delay_min,
                            self.configuration.delay_max)  # delay between requests in milliseconds
            time.sleep(delay / 1000)  # sleep for delay ms to prevent getting blocked

            # retrieve data
            response = session.get(self.uri)

            if response.ok:
                logger.info("Successfully retrieved data for entity " + str(self) + ".")

                if self.configuration.raw_download:
                    # raw download
                    self.output_parameters[self.configuration.raw_parameter] = response.content
                else:
                    # JSON API call
                    # deserialize JSON string
                    json_response = json.loads(response.text)
                    # extract parameters according to parameter mapping
                    self._extract_output_parameters(json_response)

                # execute post_request_callbacks
                for callback in self.configuration.post_request_callbacks:
                    result = callback(self)
                    # check if callback implements filter
                    if isinstance(result, bool):
                        if not result:
                            logger.info("Entity removed because of filter callback " + str(callback) + ": " + str(self))
                            return False

                    return True

            else:
                logger.error("Error " + str(response.status_code) + ": Could not retrieve data for entity " + str(self)
                             + ". Response: " + str(response.content))
                return False

        except (gaierror,
                ConnectionError,
                MaxRetryError,
                NewConnectionError):
            logger.error("An error occurred while retrieving data for entity  " + str(self) + ".")

    def _extract_output_parameters(self, json_response):
        """
        Extracts and saves all parameters defined in the output parameter mapping.
        :param json_response: The API response as JSON object.
        """

        # extract data for all parameters according to access path defined in the entity configuration
        for parameter in self.configuration.output_parameter_mapping.keys():
            parameter_filter = self.configuration.output_parameter_mapping[parameter]
            filter_result = Entity.apply_filter(json_response, parameter_filter)
            self.output_parameters[parameter] = filter_result

    @staticmethod
    def apply_filter(json_response, parameter_filter):
        """
        Use an access path (e.g., ["user", "first_name"]) to filter a nested dictionary.
        :param json_response: The JSON response to filter.
        :param parameter_filter: A list with keys for filtering a nested dictionary
            or with the list matching operator "*" followed by an optional parameter mapping for the list elements.
        :return: The extracted value if the filter has successfully been applied 
            (can be a simple value, dict, or list), None otherwise.
        """

        # start with whole JSON response
        filtered_response = json_response

        # apply the filter path
        for pos in range(len(parameter_filter)):
            current_filter = parameter_filter[pos]

            if current_filter == "*":  # list matching operator
                extracted_list = []
                if isinstance(filtered_response, list):
                    if pos == len(parameter_filter) - 1:  # if no further arguments are provided, save complete list
                        for element in filtered_response:
                            extracted_list.append(element)
                    elif pos == len(parameter_filter) - 2:  # next element is mapping for list element parameters
                        if isinstance(parameter_filter[pos + 1], dict):
                            list_element_filter = parameter_filter[pos + 1]
                            for element in filtered_response:
                                filtered_element = OrderedDict.fromkeys(list_element_filter.keys())
                                for parameter in filtered_element.keys():
                                    filtered_element[parameter] = \
                                        Entity.apply_filter(element, list_element_filter[parameter])
                                extracted_list.append(filtered_element)
                        else:
                            raise IllegalArgumentError("The list matching operator must be succeeded by a filter "
                                                       "object.")
                    else:
                        raise IllegalArgumentError("The list matching operator must be the last or second-last element "
                                                   "of  the filter path.")
                else:
                    raise IllegalArgumentError("List matching operator reached, but current position in response is "
                                               "not a list.")
                # return extracted list as defined by the list matching operator
                return extracted_list

            else:
                # normal filter path
                if not isinstance(current_filter, list) and not isinstance(current_filter, dict):
                    try:
                        # filter may be an index for a list
                        if isinstance(filtered_response, list) and Entity.parsable_as_int(current_filter):
                            index = int(current_filter)
                            filtered_response = filtered_response[index]
                        else:
                            # use current string as dictionary key to filter the response
                            filtered_response = filtered_response[current_filter]
                    except KeyError:
                        logger.error("Could not apply filter <" + str(current_filter) + "> to response "
                                     + str(filtered_response) + ".")
                        return None
                else:
                    raise IllegalArgumentError("A filter path must only contain filter strings or the list matching "
                                               "operator (optionally followed by a filter object).")

        return filtered_response

    @staticmethod
    def parsable_as_int(s):
        try:
            int(s)
            return True
        except ValueError:
            return False

    def execute_chained_request(self, chained_request_config):
        """
        Execute a chained request after retrieving the data for this entity.
        :param chained_request_config: The configuration to use for the chained request.
        :return: The entities retrieved using the chained request.
        """

        # check if provided configuration has same name as defined for chained request in own configuration
        if self.configuration.chained_request_name == chained_request_config.name:
            # get input parameters for chained request from input and output parameters of this entity
            try:
                selected_input_parameters = self.configuration.chained_request_input_parameters["input_parameters"]
                selected_output_parameters = self.configuration.chained_request_input_parameters["output_parameters"]

                # simple input parameters for chained request selected from input and output parameters of this entity
                input_parameters_chained_request = {}
                # the operator "._" can be used to flatten a list output parameter for the chained request
                flatten_parameters_chained_request = {}

                for parameter in selected_input_parameters:
                    if parameter in self.input_parameters.keys():
                        input_parameters_chained_request[parameter] = self.input_parameters[parameter]
                    else:
                        raise IllegalConfigurationError("Input parameter for chained request not found: "
                                                        + str(parameter))

                for parameter in selected_output_parameters:
                    if "._" in parameter:  # flatten operator
                        # get parameter that should be flattened
                        flatten_parameter_match = FLATTEN_OPERATOR_REGEX.match(parameter)
                        if flatten_parameter_match:
                            flatten_parameter = flatten_parameter_match.group(1)
                            # get parameter to flatten from output parameters of this entity
                            parameter_to_flatten_list = self.output_parameters[flatten_parameter]
                            if parameter_to_flatten_list:
                                if isinstance(parameter_to_flatten_list, list):  # only lists can be flattened
                                    flatten_parameters_chained_request[flatten_parameter] = parameter_to_flatten_list
                                else:
                                    raise IllegalConfigurationError(
                                        "Parameter should be flattened, but is not a list: " + str(parameter))
                        else:
                            raise IllegalConfigurationError("Wrong usage of flatten operator: Expected: <parameter>._ "
                                                            "Actual: " + str(parameter))
                    else:  # simple parameter
                        if parameter in self.output_parameters.keys():
                            input_parameters_chained_request[parameter] = self.output_parameters[parameter]
                        else:
                            raise IllegalConfigurationError(
                                "Input parameter for chained request not found: " + str(parameter))

                chained_request_entities = EntityList(chained_request_config)

                if len(flatten_parameters_chained_request) > 0:  # flatten parameters defined
                    # we only support one flatten operator in the input parameter mapping for the chained request
                    if len(flatten_parameters_chained_request) > 1:
                        raise IllegalConfigurationError(
                            "Only one flatten operator supported, but " + str(len(flatten_parameters_chained_request))
                            + " provided.")

                    for flatten_parameter in flatten_parameters_chained_request.keys():
                        parameter_to_flatten_list = flatten_parameters_chained_request[flatten_parameter]
                        if len(parameter_to_flatten_list) > 0:
                            inner_parameters = parameter_to_flatten_list[0].keys()
                            # check if inner parameter name conflicts with existing input parameters for chained request
                            for inner_parameter in inner_parameters:
                                if inner_parameter in input_parameters_chained_request.keys():
                                    raise IllegalConfigurationError("Inner parameter " + inner_parameter + " of "
                                        + str(flatten_parameter) + " already exists in list of chained input parameters.")
                            # extract inner parameters and combine them with outer parameters to flatten the list
                            for list_element in parameter_to_flatten_list:
                                flattened_input_parameters_chained_request = {**input_parameters_chained_request}
                                for inner_parameter in inner_parameters:
                                    flattened_input_parameters_chained_request[inner_parameter] = \
                                        list_element[inner_parameter]
                                chained_request_entities.add(Entity(chained_request_config, flattened_input_parameters_chained_request))

                else:  # no flatten parameters defined
                    chained_request_entities.add(Entity(chained_request_config, input_parameters_chained_request))

            except KeyError as e:
                raise IllegalConfigurationError("Reading chained request from configuration failed: Parameter "
                                                + str(e) + " not found.")
        else:
            raise IllegalArgumentError("Configuration <" + str(chained_request_config.name) + "> provided, but <"
                                       + str(self.configuration.chained_request_name) + "> needed for chained request.")

        # retrieve data for chained entities
        chained_request_entities.retrieve_data()
        # return chained entities
        return chained_request_entities


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
        self.list = []
        # session for data retrieval
        self.session = requests.Session()
        # index of first element to import from input_file (default: 0)
        self.start_index = start_index
        # number of elements to import from input_file (default: 0, meaning max.)
        self.chunk_size = chunk_size

    def add(self, entities):
        if isinstance(entities, Entity):
            self.list.append(entities)
        elif isinstance(entities, EntityList):
            self.list = self.list + entities.list
        else:
            raise IllegalArgumentError("Argument must be object of class Entity or class EntityList.")

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
                    new_entity = Entity(self.configuration, input_parameter_values)

                    # if ignore_input_duplicates is configured, check if entity already exists
                    if self.configuration.ignore_input_duplicates:
                        entity_exists = False
                        for entity in self.list:
                            if entity.equals(new_entity):
                                entity_exists = True
                        if not entity_exists:
                            # add new entity to list
                            self.list.append(new_entity)
                    else:  # ignore_input_duplicates is false
                        # add new entity to list
                        self.list.append(new_entity)
                else:
                    raise IllegalArgumentError("Wrong CSV format.")

                current_index += 1

        logger.info(str(len(self.list)) + " entities have been imported.")

    def retrieve_data(self):
        """
        Retrieve data for all entities in the list.
        """
        # retrieve data and filter list according to the return value of entity.retrieve_data
        # (may be false, e.g., because of filter callback)

        if self.configuration.apply_output_filter:
            self.list = [entity for entity in self.list if entity.retrieve_data(self.session)]
        else:
            for entity in self.list:
                entity.retrieve_data(self.session)

        logger.info("Data for " + str(len(self.list)) + " entities has been saved.")

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
            for entity in self.list:
                chained_request_entities.add(entity.execute_chained_request(chained_request_config))
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

        if len(self.list) == 0:
            logger.info("Nothing to export.")
            return

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        if self.chunk_size != 0:
            filename = '{0}_{1}-{2}.csv'.format(self.configuration.name, str(self.start_index),
                                                str(self.start_index + min(len(self.list), self.chunk_size) - 1))
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
            for entity in self.list:
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

            for entity in self.list:
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

            logger.info(str(len(self.list)) + ' entities have been exported.')

    def save_raw_files(self, output_dir):
        """
        Export raw content from entities to files.
        :param output_dir: Target directory for exported files.
        """

        if len(self.list) == 0:
            logger.info("Nothing to export.")
            return

        output_dir = os.path.join(output_dir, self.configuration.name)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        logger.info('Exporting raw content of entities to directory ' + str(output_dir) + '...')
        for entity in self.list:
            if not entity.configuration.raw_download:
                raise IllegalConfigurationError("Raw download not configured for entity " + str(entity))

            if entity.output_parameters[entity.configuration.raw_parameter] is not None:
                if "dest_path" not in entity.output_parameters.keys() or not entity.output_parameters["dest_path"]:
                    raise IllegalConfigurationError("Destination path not configured for entity " + str(entity))

                # join path to target file, create missing directories
                dest_file = os.path.join(output_dir, entity.output_parameters["dest_path"])
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

        logger.info("Raw content of " + str(len(self.list)) + ' entities has been exported.')
