""" Callbacks to extract parameters from an API response """

import logging
import re

from dateutil import parser
from util.regex import IMPORT_STATEMENT_REGEX, PACKAGE_DECLARATION_REGEX, PLACEHOLDER_REGEX, LINE_COMMENT_REGEX, \
    WHITESPACE_REGEX, MULTILINE_COMMENT_REGEX

# get root logger
logger = logging.getLogger('api-retriever_logger')


#########################
# pre_request_callbacks #
#########################

def validate_code_block_normalization(entity):
    code_block = str(entity.validation_parameters["code_block"])
    code_block_normalized = str(entity.validation_parameters["code_block_normalized"])

    if _normalize_java(code_block) == code_block_normalized:
        logger.info("Normalization successfully validated for entity " + str(entity))
    else:
        logger.error("Validation of normalization failed for entity " + str(entity))


##########################
# post_request_callbacks #
##########################

def extract_parameters(entity, json_response):
    """
    Default callback that extracts and saves all parameters defined in the output parameter mapping
    and validates all validation parameters.
    :param entity: the entity for which the request to the API has been made 
    :param json_response: the API response as JSON object
    """

    # extract data for all parameters according to access path defined in the entity configuration
    for parameter in entity.configuration.output_parameter_mapping.keys():
        mapping = entity.configuration.output_parameter_mapping[parameter]

        if mapping[0] == "*":  # mapping starts with asterisk -> root of JSON response is list of elements

            if len(mapping) == 1:  # if no further arguments are provided, save complete list elements
                for element in json_response:
                    entity.output_parameters[parameter] = element
                return

            if len(mapping) == 2:  # second element is filter
                inner_parameters = mapping[1]
                parameter_values = []
                for element in json_response:
                    inner_output_parameters = dict.fromkeys(inner_parameters.keys())
                    for inner_parameter in inner_parameters.keys():
                        inner_access_path = inner_parameters[inner_parameter]
                        try:
                            parameter_value = _filter_nested_dictionary(element, inner_access_path)
                        except KeyError:
                            logger.error("Could not retrieve data for parameter " + parameter
                                         + " of entity " + str(entity))
                            parameter_value = None

                        inner_output_parameters[inner_parameter] = parameter_value

                    parameter_values.append(inner_output_parameters)

                entity.output_parameters[parameter] = parameter_values
                return

        else:  # root of JSON response is dictionary
            access_path = mapping
            parameter_value = _filter_nested_dictionary(json_response, access_path)

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


def sort_commits(entity):
    # parse commit date strings (ISO 8601) into a python datetime object (see http://stackoverflow.com/a/3908349)
    for commit in entity.output_parameters["commits"]:
        commit["commit_date"] = parser.parse(commit["commit_date"])

    # sort commits (oldest commits first)
    entity.output_parameters["commits"] = sorted(entity.output_parameters["commits"], key=lambda c: c["commit_date"])

    # convert commit dates back to string representation
    for commit in entity.output_parameters["commits"]:
        commit["commit_date"] = str(commit["commit_date"])


# def filter_commits_with_code_block(entity):
#     # search for match of code_block in commit diff
#     pass


# def get_commit_files(entity):
#     commit_configuration = EntityConfiguration("config/gh_repo_commits_files.json")
#     session = requests.Session()
#
#     for commit in entity.output_parameters["commits"]:
#         commit_entity = Entity(
#             commit_configuration,
#             {
#                 "repo_name": entity.input_parameters["repo_name"],
#                 "path": entity.input_parameters["path"],
#                 "commit_sha": commit["commit_sha"],
#                 "code_block_normalized": entity.validation_parameters["code_block_normalized"]
#             }
#         )
#
#         commit_entity.retrieve_data(session)
#
#         logger.info(commit_entity)



# def filter_commits_if_code_block_in_patch(entity, json_response):
#     for file in entity.output_parameters["files"]:
#         if file["filename"] == entity.input_parameters["path"]:
#             patch = file.get("patch", None)
#             if not patch:
#                 return None
#
#             patch_norm = _normalize(_get_added_lines(patch))
#
#             if entity.validation_parameters.code_block_norm in patch_norm:
#                 commit.diff = patch
#                 commit.diff_norm = patch_norm
#                 return commit


####################
# helper functions #
####################

def _filter_nested_dictionary(dictionary, access_path):
    """
    Use an access path (e.g., ["user", "first_name"]) to filter a nested dictionary.
    :param dictionary: the dictionary to filter
    :param access_path: a list with keys for filtering the nested dictionary
    :return: the resulting value
    :raises: KeyError if filtering using access_path is not possible in dictionary
    """

    # start with whole dictionary
    result = dictionary

    # loop through access path and filter dictionary accordingly
    for step in access_path:
        result = result[step]

    return result


def _normalize_java(source_code):
    """
    Normalize a string with Java source code.
    (e.g., remove comments, imports, package declarations, whitespaces, etc.)
    :param source_code: string with Java code
    :return: normalized source code
    """

    # TODO: add test cases

    normalized_code_block = ""

    # start with line-based normalization
    lines = source_code.split('\n')
    for line in lines:
        # first convert line to lower case
        normalized_line = line.lower()

        # ignore import statements, package declarations, and lines like "..."
        if IMPORT_STATEMENT_REGEX.match(normalized_line) \
                or PACKAGE_DECLARATION_REGEX.match(normalized_line) \
                or PLACEHOLDER_REGEX.match(normalized_line):
            continue

        # remove line comments
        match = re.search(LINE_COMMENT_REGEX, normalized_line)
        if match:
            normalized_line = str(match.group(1))

        # remove special characters
        normalized_line = normalized_line.replace("{", "")
        normalized_line = normalized_line.replace("}", "")
        normalized_line = normalized_line.replace(";", "")
        normalized_line = normalized_line.replace("(", "")
        normalized_line = normalized_line.replace(")", "")

        # remove whitespaces
        normalized_line = re.sub(WHITESPACE_REGEX, '', normalized_line)

        # ignore empty lines
        if normalized_line:
            if not normalized_code_block:  # empty
                normalized_code_block = normalized_line
            else:  # append normalized line separated by blank
                normalized_code_block += " " + normalized_line

    # further normalization on whole string

    # remove multiline comments
    normalized_code_block = re.sub(MULTILINE_COMMENT_REGEX, '', normalized_code_block)
    # remove remaining blanks between normalized lines
    normalized_code_block = re.sub(WHITESPACE_REGEX, '', normalized_code_block)

    return normalized_code_block


def _get_added_lines(patch):
    """
    Get lines added with a patch.
    (e.g., git diff between two versions of a file)
    :param patch: the content of the patch
    :return: the lines added by the patch
    """

    added_lines = ""

    lines = patch.split('\n')
    for line in lines:
        if line.startswith("+"):
            if not added_lines:  # empty
                added_lines = line[1:]
            else:  # append
                added_lines += line[1:] + "\n"

    return added_lines
