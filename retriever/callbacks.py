""" Callbacks to extract parameters from an API response """

import logging

from dateutil import parser
from util.data_processing import normalize_java

# get root logger
from util.exceptions import IllegalConfigurationError

logger = logging.getLogger('api-retriever_logger')


#########################
# pre_request_callbacks #
#########################

def validate_code_block_normalization(entity):
    try:
        code_block = str(entity.input_parameters["code_block"])
        code_block_normalized = str(entity.input_parameters["code_block_normalized"])

        if normalize_java(code_block) == code_block_normalized:
            logger.info("Normalization successfully validated for entity " + str(entity))
        else:
            logger.error("Validation of normalization failed for entity " + str(entity))

    except KeyError as e:
        raise IllegalConfigurationError("Input parameters missing: " + str(e))


##########################
# post_request_callbacks #
##########################

def sort_commits(entity):
    if entity.output_parameters["commits"]:
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




# if parameter in self.validation_parameters:
#     # check validation parameter
#     if not parameter_value:
#         logger.error("Validation failed for parameter " + parameter
#                      + " of entity " + str(self) + ": Empty value.")
#
#     if str(parameter_value) == str(entity.validation_parameters[parameter]):
#         logger.info("Validation successful for parameter " + parameter
#                     + " of entity " + str(entity) + ".")
#     else:
#         logger.error("Validation failed for parameter " + parameter
#                      + " of entity " + str(entity)
#                      + ": Expected: " + str(entity.validation_parameters[parameter])
#                      + ", Actual: " + str(parameter_value) + ".")
#         # save correct value
#         entity.validation_parameters[parameter] = parameter_value
