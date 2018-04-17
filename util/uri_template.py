from util.exceptions import IllegalArgumentError
from util.regex import URI_TEMPLATE_VARS_REGEX


class URITemplate(object):
    """
    Variables in an URI template are enclosed in curly braces, e.g.:
      "https://api.airbnb.com/v2/users/{host_id}?client_id={api_key}"
    """

    def __init__(self, uri_template_str):
        self.uri_template_str = uri_template_str

    def equals(self, other_uri_template):
        return self.uri_template_str == other_uri_template.uri_template_str

    def get_variables(self):
        return URI_TEMPLATE_VARS_REGEX.findall(self.uri_template_str)

    def replace_range_variable(self, range_var):
        self.uri_template_str = self.uri_template_str.replace(range_var.range_str, range_var.name)

    def replace_variables(self, variable_values):
        """
        Replace all variables in the URI template with actual values.
        :param variable_values: A dictionary with values for the variables in the URI template.
        :return: The final URI string.
        """

        uri = self.uri_template_str
        uri_variables = self.get_variables()

        for variable in uri_variables:
            value = variable_values.get(variable, None)
            if value:
                uri = uri.replace("{" + variable + "}", value)
            else:
                IllegalArgumentError("Value for URI variable " + variable + " missing.")

        return uri
