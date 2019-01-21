import json
import logging
import time

from random import randint
from _socket import gaierror

import os
from collections import OrderedDict

from urllib3.exceptions import MaxRetryError, NewConnectionError

from util.exceptions import IllegalArgumentError, IllegalConfigurationError
from util.regex import FLATTEN_OPERATOR_REGEX

# get root logger
logger = logging.getLogger('api-retriever_logger')


class Entity(object):
    """
    Class representing one API entity for which information should be retrieved over an API.
    """

    def __init__(self, configuration, input_parameter_values, predecessor):
        """
        To initialize an entity, a corresponding entity configuration together
        and values for the input parameter(s) are needed.
        :param configuration: an object of class EntityConfiguration
        :param input_parameter_values: A dictionary with values for the input parameters defined in the configuration.
        :param predecessor: predecessor in entity list
        """

        # corresponding entity configuration
        self.configuration = configuration
        # parameters needed to identify entity (or for validation)
        self.input_parameters = OrderedDict.fromkeys(configuration.input_parameters)
        # parameters that should be retrieved using the API
        self.output_parameters = OrderedDict.fromkeys(configuration.output_parameter_mapping.keys())
        # destination path for raw download
        self.destination = None

        # set values for input parameters
        for parameter in configuration.input_parameters:
            if parameter in input_parameter_values:
                self.input_parameters[parameter] = input_parameter_values[parameter]
            else:
                raise IllegalArgumentError("Illegal input parameter: " + parameter)

        # get uri for this entity from uri template in the configuration
        uri_variable_values = {
            **self.input_parameters
        }

        # add values for API keys
        for i in range(0, len(self.configuration.api_keys)):
            uri_variable_values["api_key_" + str(i+1)] = self.configuration.api_keys[i]

        # set values for range variables
        for range_var_name in configuration.range_vars:
            if not range_var_name in input_parameter_values:
                continue
            uri_variable_values[range_var_name] = input_parameter_values[range_var_name]

        self.uri = self.configuration.uri_template.replace_variables(uri_variable_values)

        # set predecessor
        self.predecessor = predecessor
        # root entity is set if range variables are used
        self.root_entity = None

        # store JSON response data (may be needed by callbacks)
        self.json_response = None

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
                result = callback(self)
                # if pre request filtering is enabled, apply filter
                if self.configuration.pre_request_callback_filter and not result:
                    return False

            # reduce request frequency as configured
            delay = randint(self.configuration.delay_min,
                            self.configuration.delay_max)  # delay between requests in milliseconds
            time.sleep(delay / 1000)  # sleep for delay ms to prevent getting blocked

            # retrieve data
            if len(self.configuration.headers) > 0:
                response = session.get(self.uri, headers=self.configuration.headers)
            else:
                response = session.get(self.uri)

            if response.ok:
                logger.info("Successfully retrieved data for entity " + str(self) + ".")

                if self.configuration.raw_download:
                    # raw download
                    self.output_parameters[self.configuration.raw_parameter] = response.content
                    # join path to destination file
                    dest_file = ""
                    for part in self.configuration.output_parameter_mapping["destination"]:
                        if part not in self.input_parameters:
                            raise IllegalConfigurationError("Destination parameter "
                                                            + part
                                                            + " not found in input parameters.")
                        dest_file = os.path.join(dest_file, self.input_parameters[part])
                    self.output_parameters["destination"] = dest_file
                else:
                    # JSON API call
                    # deserialize JSON string
                    json_response = json.loads(response.text)
                    self.json_response = json_response
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
                            if filtered_response[current_filter] is None:
                                logger.info("Result for filter " + current_filter + " was None.")
                                return "None"
                            else:
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

    def get_chained_request_entities(self, chained_request_config):
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

                chained_request_entities = list()

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
                                chained_request_entities.append(Entity(chained_request_config, flattened_input_parameters_chained_request, None))

                else:  # no flatten parameters defined
                    chained_request_entities.append(Entity(chained_request_config, input_parameters_chained_request, None))

            except KeyError as e:
                raise IllegalConfigurationError("Reading chained request from configuration failed: Parameter "
                                                + str(e) + " not found.")
        else:
            raise IllegalArgumentError("Configuration <" + str(chained_request_config.name) + "> provided, but <"
                                       + str(self.configuration.chained_request_name) + "> needed for chained request.")

        return chained_request_entities

