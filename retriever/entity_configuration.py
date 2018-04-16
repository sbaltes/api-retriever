import json
import logging

from inspect import signature
from jsmin import jsmin

from retriever import callbacks
from util.exceptions import IllegalArgumentError, IllegalConfigurationError
from util.uri_template import URITemplate

# get root logger
logger = logging.getLogger('api-retriever_logger')


class EntityConfiguration(object):
    """
    An API entity configuration specifies:
        * the input parameters for an entity
        * which information should be retrieved about an entity (-> output parameters)
        * how this information should be retrieved (uri template and api keys)
        * the pre- and post-processing that should be done (callbacks, flattening results)
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
            # the user may specify custom headers for the HTTP request
            self.headers = config_dict["headers"]
            # API keys to include in the uri_template
            self.api_keys = config_dict["api_keys"]
            # check if api key configured when required for uri_template
            uri_vars = self.uri_template.get_variables()
            for var in uri_vars:
                if var.startswith("api_key") and not self.api_keys:
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
            # optionally, dicts in the results can be flattened
            self.flatten_output = config_dict["flatten_output"]
            #  save (optional) chained request
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
        if not self.ignore_input_duplicates == other_config.ignore_input_duplicates:
            return False
        if not self.delay_min == other_config.delay_min:
            return False
        if not self.delay_max == other_config.delay_max:
            return False

        for api_key in self.api_keys:
            if api_key not in other_config.api_keys:
                return False

        for header in self.headers:
            if header not in other_config.headers:
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
