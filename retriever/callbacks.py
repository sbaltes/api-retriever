""" Callbacks to extract parameters from an API response """

import json
import logging

# get root logger
logger = logging.getLogger('api-retriever_logger')


def save_parameters(entity, response):
    """
    Default callback that extracts and saves all parameters defined in the output parameter mapping
    and validates all validation parameters.
    :param entity: the entity for which the request to the API has been made 
    :param response: the API response as text
    """

    # deserialize JSON string
    json_response = json.loads(response)

    # extract data for all parameters according to access path defined in the entity configuration
    for parameter in entity.configuration.output_parameter_mapping.keys():
        access_path = entity.configuration.output_parameter_mapping[parameter]
        # start with whole JSON response
        value = json_response
        # loop through access path and filter JSON response accordingly
        for step in access_path:
            try:
                value = value[step]
            except KeyError:
                value = None
                logger.error("Could not retrieve data for parameter " + parameter + " of entity " + str(entity))
                break

        if parameter in entity.validation_parameters:
            # check validation parameter
            if not value:
                logger.error("Validation failed for parameter " + parameter
                             + " of entity " + str(entity) + ": Empty value.")

            if str(value) == str(entity.validation_parameters[parameter]):
                logger.info("Validation successful for parameter " + parameter
                            + " of entity " + str(entity) + ".")
            else:
                logger.error("Validation failed for parameter " + parameter
                             + " of entity " + str(entity)
                             + ": Expected: " + str(entity.validation_parameters[parameter])
                             + ", Actual: " + str(value) + ".")
                # save correct value
                entity.validation_parameters[parameter] = value
        else:
            # save output parameter
            entity.output_parameters[parameter] = value

