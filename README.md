# api-retriever

Retrieve and filter data from public APIs and export it to CSV files.
Examples for supported APIs include the [GitHub API](https://developer.github.com/v3/), the [Stack Exchange API](https://api.stackexchange.com/docs), the [Google Custom Search API](https://developers.google.com/custom-search/json-api/v1/using_rest), and the [unofficial Airbnb API](https://web.archive.org/web/20170519054521/http://www.airbnbapi.org/).

[![DOI](https://zenodo.org/badge/87788115.svg)](https://zenodo.org/badge/latestdoi/87788115)

# Setup

Python 3 is required. The dependencies are specified in `requirements.txt`.
To install those dependencies execute:

    pip3 install -r requirements.txt

Optional: Setup virtual environment with [pyenv](https://github.com/pyenv/pyenv#homebrew-on-mac-os-x) 
and [virtualenv](https://github.com/pyenv/pyenv-virtualenv) before executing the above command:

    pyenv install 3.6.5
    pyenv virtualenv 3.6.5 api-retriever_3.6.5
    pyenv activate api-retriever_3.6.5
    
    pip3 install --upgrade pip


# Usage

Basic usage:

    python3 api-retriever.py -i <path_to_input_file> -o <path_to_output_dir> -c <path_to_config_file>

Call without parameters to get information about possible parameters:

    python3 api-retriever.py
    
    usage: api-retriever.py [-h] -i INPUT_FILE -o OUTPUT_DIR -c CONFIG_FILE
                        [-cd CONFIG_DIR] [-d DELIMITER] [-si START_INDEX]
                        [-cs CHUNK_SIZE]
    api-retriever.py: error: the following arguments are required: -i/--input-file, -o/--output-dir, -c/--config-file


# Configuration

The API retriever is configured using a JSON file, which must have the following structure:

    {
      "input_parameters": [],
      "ignore_input_duplicates": false,
      "uri_template": "",
      "headers": {},
      "api_keys": [],
      "delay": [],
      "pre_request_callbacks": [],
      "pre_request_callback_filter": false,
      "output_parameter_mapping": {},
      "post_request_callbacks": [],
      "post_request_callback_filter": false,
      "flatten_output": false,
      "chained_request": {}
    }

In the following, we use examples from different APIs to demonstrate the configuration parameters.
Let's start with a simple query that retrieves the licenses for a list of GitHub repositories.

## Example 1: Retrieve license of GitHub repositories

First of all, the value of property `input_parameters` must be an array containing the column names of the input CSV file.
In our example, the CSV file just contains one column with the names of the GitHub repositories we want to retrieve the license of.
If parameter `ignore_input_duplicates` is set to true, duplicate rows in the input file will be ignored (in this case multiple rows with the same repo name).

    {
      "input_parameters": ["repo_name"],
      "ignore_input_duplicates": true,
      // ...
    }

A corresponding CSV file could look like this:

| repo_name                          |
|------------------------------------|
| sbaltes/api-retriever              |
| sbaltes/git-log-extractor          |
| sotorrent/so-posthistory-extractor |
| ...                                |

The next parameter we are going to configure is probably the most important one.
The `uri_template` specifies how the resources is accessed.
The documentation for the GitHub repo/license API endpoint can be found [here](https://developer.github.com/v3/licenses/).
In the template, variable names are enclosed in curly braces.
In this example, the `repo_name` from the input file will be inserted into the configured position.
Most APIs use keys to authenticate users.
As some APIs require more than one key (e.g., Google Custom Search, see below), the keys are configured using an array.
In the URI template, the API keys can then be identified using their position in the array: `api_key_1` corresponds to the first element in that array, `api_key_2` to the second, and so on.

    {
      "input_parameters": ["repo_name"],
      "ignore_input_duplicates": true,
      "uri_template": "https://api.github.com/repos/{repo_name}?access_token={api_key_1}",
      "api_keys": ["8b1ef5abd3524fa98b4763384879a1ce201301d1"], // add API key here
      "headers": {},
      // ...
    }
 
It is also possible to specify custom header fields.
Retrieving the license of a repository, for example, used to be only available as an [API preview](https://developer.github.com/v3/previews/).
In that case, a custom header for the request can be configured as follows:

    {
      // ...
      "headers": {
        "Accept": "application/vnd.github.drax-preview+json"
      },
      // ...
    }

To prevent being blocked due to a large amount of queries in a short time frame, a random `delay` between the request can be configured.
In this example, the api-retriever will wait for 100 up to 2000 milliseconds before each request.
The delay is chosen randomly from that interval each time a request is made.
Pre-request callbacks are not needed for the current example and will be explained later.

    {
      "input_parameters": ["repo_name"],
      "ignore_input_duplicates": true,
      "uri_template": "https://api.github.com/repos/{repo_name}?access_token={api_key_1}",
      "api_keys": ["8b1ef5abd3524fa98b4763384879a1ce201301d1"], // add API key here
      "headers": {},
      "delay": [100, 2000],
      "pre_request_callbacks": [],
      // ...
    }

The next important parameter is the `output_parameter_mapping`.
This mapping is a JSON object with property definitions of the following structure:

    "<name_in_output>": [<path_in_json_response>]

Each property name in that object corresponds to a column in the output CSV file.
Since the JSON response is likely to contain [many fields](https://api.github.com/repos/sbaltes/api-retriever) not needed for the output, specific parts of the response can be selected.
In our example, the JSON response contains a property named `license` that is structured as follows (corresponding [query](https://api.github.com/repos/sbaltes/api-retriever)):

    // ...
    "license": {
      "key": "apache-2.0",
      "name": "Apache License 2.0",
      "spdx_id": "Apache-2.0",
      "url": "https://api.github.com/licenses/apache-2.0"
    },
    // ...

In our example, we store the property `key` of that JSON object in the output parameter `license` (which corresponds to a column `license` in the output CSV file):

    {
      "input_parameters": ["repo_name"],
      "ignore_input_duplicates": true,
      "uri_template": "https://api.github.com/repos/{repo_name}?access_token={api_key_1}",
      "api_keys": ["8b1ef5abd3524fa98b4763384879a1ce201301d1"], // add API key here
      "headers": {},
      "delay": [100, 2000],
      "pre_request_callbacks": [],
      "pre_request_callback_filter": false,
      "output_parameter_mapping": {
        "license": ["license", "key"]
      },
      // ...
    }

Finally, one can configure output filters, post request callbacks, flattened outputs, and chained requests. Those properties will be described in the examples below.
The final configuration to retrieve the licenses for a list of GitHub repositories looks like this (corresponding [configuration file](https://github.com/sbaltes/api-retriever/blob/master/config/gh_repo___license.json)):

    {
      "input_parameters": ["repo_name"],
      "ignore_input_duplicates": true,
      "uri_template": "https://api.github.com/repos/{repo_name}?access_token={api_key_1}",
      "api_keys": ["8b1ef5abd3524fa98b4763384879a1ce201301d1"], // add API key here
      "headers": {},
      "delay": [100, 2000],
      "pre_request_callbacks": [],
      "pre_request_callback_filter": false,
      "output_parameter_mapping": {
        "license": ["license", "key"]
      },
      "post_request_callbacks": [],
      "post_request_callback_filter": false,
      "flatten_output": false,
      "chained_request": {}
    }

The resulting CSV file would look like this:

| repo_name                          | license    |
|------------------------------------|------------|
| sbaltes/api-retriever              | apache-2.0 |
| sbaltes/git-log-extractor          | gpl-3.0    |
| sotorrent/so-posthistory-extractor | apache-2.0 |
| ...                                | ...        |


## Example 2: Retrieve files from GitHub repositories

In the next example, we are going to retrieve files from GitHub repositories.
The input parameters are the `repo_name`, the `path` to the file within that repo, and the `branch` in which the file can be found.
An input file could look like this:

| repo_name                          | path                                                          | branch |
|------------------------------------|---------------------------------------------------------------|--------|
| sbaltes/api-retriever              | retriever/entity.py                                           | master |
| sbaltes/git-log-extractor          | clone_projects.sh                                             | master |
| sotorrent/so-posthistory-extractor | src/de/unitrier/st/soposthistory/blocks/PostBlockVersion.java | master |
| ...                                | ...                                                           | ...    |

We don't need an API key to retrieve files from GitHub, we can just use their raw interface:

    {
      "input_parameters": ["repo_name", "path", "branch"],
      "ignore_input_duplicates": true,
      "uri_template": "https://raw.githubusercontent.com/{repo_name}/{branch}/{path}",
      "api_keys": [],
      "headers": {},
      "delay": [40, 1000],
      "pre_request_callbacks": [],
      "pre_request_callback_filter": false,
      "output_parameter_mapping": {
        "content": ["<raw_response>"],
        "destination": ["repo_name", "path"]
      },
      "post_request_callbacks": [],
      "post_request_callback_filter": false,
      "flatten_output": false,
      "chained_request": {}
    }

The only notable difference to the previous example is the first output parameter:

    "content": ["<raw_response>"]
    
Using the mapping `<raw_response>`, we can configure the api-retriever to save the complete raw response instead of first parsing it as JSON content and then applying the configured filter.
However, when `<raw_response>` is configured, a destination path for each retrieved file is needed.
The api-retriever searches for a `destination` parameter in the output parameter mapping and joins the configured columns from the input data.
In our example, the file `retriever/entity.py` from repo `sbaltes/api-retriever` would we written to the path `<path_to_output_dir>/sbaltes/api-retriever/retriever/entity.py`.

We can also configure a post request callback (executed after the request has been made) to set a custom path:

    "post_request_callbacks": ["set_destination_path"],

In that case, the api-retriever searches for a function named `set_destination_path` in `retriever/callbacks.py` and passes the retrieved entity to that function.
A function modifying the output path could look like this:

    def set_destination_path(entity):
        """
        Add destination path for raw content to output parameters of an entity.
        See entity configuration: gh_repo_path_branch___file
        :param entity:
        """
        if entity.output_parameters[entity.configuration.raw_parameter] is None:
            return
        repo_name = entity.input_parameters["repo_name"].split("/")
        user = repo_name[0]
        repo = repo_name[1]
        path = entity.input_parameters["path"].replace("/", " ")
        # add destination path to output
        entity.output_parameters["destination"] = os.path.join(user, repo, path)

In that case, the files would be written to `<path_to_output_dir>/<repo_name>/<converted_file_name>`, where the converted file name is the input path where slashes have been replaces with blanks.
In case of the file `retriever/entity.py`, the converted path would be `retriever entity.py`.

