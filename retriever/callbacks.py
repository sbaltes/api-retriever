""" Callbacks to extract parameters from an API response """

import logging

from dateutil import parser
from util.uri_template import URITemplate


# get root logger
logger = logging.getLogger('api-retriever_logger')


def save_parameters(entity, json_response):
    """
    Default callback that extracts and saves all parameters defined in the output parameter mapping
    and validates all validation parameters.
    :param entity: the entity for which the request to the API has been made 
    :param json_response: the API response as JSON object
    """

    # extract data for all parameters according to access path defined in the entity configuration
    for parameter in entity.configuration.output_parameter_mapping.keys():
        access_path = entity.configuration.output_parameter_mapping[parameter]

        if access_path[0] == "*":  # access path starts with asterisk -> root of JSON response is list of elements

            if len(access_path) == 1:  # if no further arguments are provided, save complete list elements
                for element in json_response:
                    entity.output_parameters[parameter] = element
            elif len(access_path) == 2:  # second element is filter
                inner_parameters = access_path[1]
                parameter_values = []
                for element in json_response:
                    inner_output_parameters = dict.fromkeys(inner_parameters.keys())
                    for inner_parameter in inner_parameters.keys():
                        inner_access_path = inner_parameters[inner_parameter]
                        try:
                            parameter_value = _filter_json(element, inner_access_path)
                        except KeyError:
                            logger.error("Could not retrieve data for parameter " + parameter
                                         + " of entity " + str(entity))
                            parameter_value = None

                        inner_output_parameters[inner_parameter] = parameter_value

                    parameter_values.append(inner_output_parameters)

                entity.output_parameters[parameter] = parameter_values

        else:  # root of JSON response is dictionary
            parameter_value = _filter_json(json_response, access_path)

            if parameter in entity.validation_parameters:
                # check validation parameter
                if not parameter_value:
                    logger.error("Validation failed for parameter " + parameter
                                 + " of entity " + str(entity) + ": Empty value.")

                if str(parameter_value) == str(entity.validation_parameters[parameter]):
                    logger.info("Validation successful for parameter " + parameter
                                + " of entity " + str(entity) + ".")
                else:
                    logger.error("Validation failed for parameter " + parameter
                                 + " of entity " + str(entity)
                                 + ": Expected: " + str(entity.validation_parameters[parameter])
                                 + ", Actual: " + str(parameter_value) + ".")
                    # save correct value
                    entity.validation_parameters[parameter] = parameter_value
            else:
                # save output parameter
                entity.output_parameters[parameter] = parameter_value


def gh_snippet_commits(entity, json_response):
    save_parameters(entity, json_response)

    for commit in entity.output_parameters["commits"]:
        # parse string with ISO 8601 commit date into a python datetime object (see http://stackoverflow.com/a/3908349)
        commit["commit_date"] = parser.parse(commit["commit_date"])

    # sort commits (oldest commits first)
    entity.output_parameters["commits"] = sorted(entity.output_parameters["commits"], key=lambda c: c["commit_date"])

    # search for match of code_block in commit diff
    uri_template = URITemplate("https://api.github.com/repos/{repo_name}/commits/{commit_sha}?access_token={api_key}")



def _filter_json(json_response, access_path):
    """
    Use an access path (e.g., ["user", "first_name"]) to filter a JSON object (dictionary).
    :param json_response: the json object to filter
    :param access_path: a list with keys for filtering the dictionary
    :return: the resulting value
    :raises: KeyError if filtering using access_path is not possible in json_response
    """

    # start with whole JSON response
    result = json_response

    # loop through access path and filter JSON response accordingly
    for step in access_path:
        result = result[step]

    return result
