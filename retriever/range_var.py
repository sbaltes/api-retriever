from util.exceptions import IllegalConfigurationError


class RangeVar(object):
    """
    Class for range variables in URI pattern.
    {name|start;stop;step}
    """
    def __init__(self, range_str):
        self.range_str = range_str
        parts = range_str.split("|")
        if len(parts) != 2:
            raise IllegalConfigurationError("Illegal range string: " + range_str)
        self.name = parts[0]
        range_parts = parts[1].split(";")
        if len(range_parts) != 3:
            raise IllegalConfigurationError("Illegal range string: " + range_str)
        self.start = int(range_parts[0])
        self.stop = int(range_parts[1])
        self.step = int(range_parts[2])
