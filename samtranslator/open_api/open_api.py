import copy
import re
from typing import Any, Iterator, Optional

from samtranslator.model.intrinsics import ref, make_conditional, is_intrinsic, is_intrinsic_no_value
from samtranslator.model.exceptions import InvalidDocumentException, InvalidTemplateException
from samtranslator.utils.py27hash_fix import Py27Dict, Py27UniStr
import json


class OpenApiEditor(object):
    """
    Wrapper class capable of parsing and generating OpenApi JSON.  This implements OpenApi spec just enough that SAM
    cares about. It is built to handle "partial Swagger" ie. Swagger that is incomplete and won't
    pass the Swagger spec. But this is necessary for SAM because it iteratively builds the Swagger starting from an
    empty skeleton.

    NOTE (hawflau): To ensure the same logical ID will be generated in Py3 as in Py2 for AWS::Serverless::HttpApi resource,
    we have to apply py27hash_fix. For any dictionary that is created within the swagger body, we need to initiate it
    with Py27Dict() instead of {}. We also need to add keys into the Py27Dict instance one by one, so that the input
    order could be preserved. This is a must for the purpose of preserving the dict key iteration order, which is
    essential for generating the same logical ID.
    """

    _X_APIGW_INTEGRATION = "x-amazon-apigateway-integration"
    _X_APIGW_TAG_VALUE = "x-amazon-apigateway-tag-value"
    _X_APIGW_CORS = "x-amazon-apigateway-cors"
    _X_APIGW_ENDPOINT_CONFIG = "x-amazon-apigateway-endpoint-configuration"
    _SERVERS = "servers"
    _CONDITIONAL_IF = "Fn::If"
    _X_ANY_METHOD = "x-amazon-apigateway-any-method"
    _ALL_HTTP_METHODS = ["OPTIONS", "GET", "HEAD", "POST", "PUT", "DELETE", "PATCH"]
    _DEFAULT_PATH = "$default"

    def __init__(self, doc):  # type: ignore[no-untyped-def]
        """
        Initialize the class with a swagger dictionary. This class creates a copy of the Swagger and performs all
        modifications on this copy.

        :param dict doc: OpenApi document as a dictionary
        :raises InvalidDocumentException: If the input OpenApi document does not meet the basic OpenApi requirements.
        """
        if not OpenApiEditor.is_valid(doc):
            raise InvalidDocumentException(
                [
                    InvalidTemplateException(
                        "Invalid OpenApi document. Invalid values or missing keys for 'openapi' or 'paths' in 'DefinitionBody'."
                    )
                ]
            )

        self._doc = copy.deepcopy(doc)
        self.paths = self._doc["paths"]
        self.security_schemes = self._doc.get("components", Py27Dict()).get("securitySchemes", Py27Dict())
        self.definitions = self._doc.get("definitions", Py27Dict())
        self.tags = self._doc.get("tags", [])
        self.info = self._doc.get("info", Py27Dict())

    def get_conditional_contents(self, item):  # type: ignore[no-untyped-def]
        """
        Returns the contents of the given item.
        If a conditional block has been used inside the item, returns a list of the content
        inside the conditional (both the then and the else cases). Skips {'Ref': 'AWS::NoValue'} content.
        If there's no conditional block, then returns an list with the single item in it.

        :param dict item: item from which the contents will be extracted
        :return: list of item content
        """
        contents = [item]
        if isinstance(item, dict) and self._CONDITIONAL_IF in item:
            contents = item[self._CONDITIONAL_IF][1:]
            contents = [content for content in contents if not is_intrinsic_no_value(content)]
        return contents

    def has_path(self, path, method=None):  # type: ignore[no-untyped-def]
        """
        Returns True if this Swagger has the given path and optional method
        For paths with conditionals, only returns true if both items (true case, and false case) have the method.

        :param string path: Path name
        :param string method: HTTP method
        :return: True, if this path/method is present in the document
        """
        if path not in self.paths:
            return False

        method = self._normalize_method_name(method)  # type: ignore[no-untyped-call]
        if method:
            for path_item in self.get_conditional_contents(self.paths.get(path)):  # type: ignore[no-untyped-call]
                if not path_item or method not in path_item:
                    return False
        return True

    def is_integration_function_logical_id_match(self, path_name, method_name, logical_id):  # type: ignore[no-untyped-def]
        """
        Returns True if the function logical id in a lambda integration matches the passed
        in logical_id.
        If there are conditionals (paths, methods, uri), returns True only
        if they all match the passed in logical_id. False otherwise.
        If the integration doesn't exist, returns False
        :param path_name: name of the path
        :param method_name: name of the method
        :param logical_id: logical id to compare against
        """
        if not self.has_integration(path_name, method_name):  # type: ignore[no-untyped-call]
            return False
        method_name = self._normalize_method_name(method_name)  # type: ignore[no-untyped-call]

        for method_definition in self.iter_on_method_definitions_for_path_at_method(path_name, method_name, False):  # type: ignore[no-untyped-call]
            integration = method_definition.get(self._X_APIGW_INTEGRATION, Py27Dict())

            # Extract the integration uri out of a conditional if necessary
            uri = integration.get("uri")
            if not isinstance(uri, dict):
                return False
            for uri_content in self.get_conditional_contents(uri):  # type: ignore[no-untyped-call]
                arn = uri_content.get("Fn::Sub", "")

                # Extract lambda integration (${LambdaName.Arn}) and split ".Arn" off from it
                regex = r"([A-Za-z0-9]+\.Arn)"
                matches = re.findall(regex, arn)
                # Prevent IndexError when integration URI doesn't contain .Arn (e.g. a Function with
                # AutoPublishAlias translates to AWS::Lambda::Alias, which make_shorthand represents
                # as LogicalId instead of LogicalId.Arn).
                # TODO: Consistent handling of Functions with and without AutoPublishAlias (see #1901)
                if not matches or matches[0].split(".Arn")[0] != logical_id:
                    return False

        return True

    def method_has_integration(self, method):  # type: ignore[no-untyped-def]
        """
        Returns true if the given method contains a valid method definition.
        This uses the get_conditional_contents function to handle conditionals.

        :param dict method: method dictionary
        :return: true if method has one or multiple integrations
        """
        for method_definition in self.get_conditional_contents(method):  # type: ignore[no-untyped-call]
            if self.method_definition_has_integration(method_definition):  # type: ignore[no-untyped-call]
                return True
        return False

    def method_definition_has_integration(self, method_definition):  # type: ignore[no-untyped-def]
        """
        Checks a method definition to make sure it has an apigw integration

        :param dict method_defintion: method definition dictionary
        :return: True if an integration exists
        """
        if method_definition.get(self._X_APIGW_INTEGRATION):
            return True
        return False

    def has_integration(self, path, method):  # type: ignore[no-untyped-def]
        """
        Checks if an API Gateway integration is already present at the given path/method.
        For paths with conditionals, it only returns True if both items (true case, false case) have the integration

        :param string path: Path name
        :param string method: HTTP method
        :return: True, if an API Gateway integration is already present
        """
        method = self._normalize_method_name(method)  # type: ignore[no-untyped-call]

        if not self.has_path(path, method):  # type: ignore[no-untyped-call]
            return False

        for path_item in self.get_conditional_contents(self.paths.get(path)):  # type: ignore[no-untyped-call]
            method_definition = path_item.get(method)
            if not (isinstance(method_definition, dict) and self.method_has_integration(method_definition)):  # type: ignore[no-untyped-call]
                return False
        # Integration present and non-empty
        return True

    def add_path(self, path: str, method: Optional[str] = None) -> None:
        """
        Adds the path/method combination to the Swagger, if not already present

        :param string path: Path name
        :param string method: HTTP method
        :raises InvalidDocumentException: If the value of `path` in Swagger is not a dictionary
        """
        method = self._normalize_method_name(method)  # type: ignore[no-untyped-call]

        path_dict = self.paths.setdefault(path, Py27Dict())

        if not isinstance(path_dict, dict):
            # Either customers has provided us an invalid Swagger, or this class has messed it somehow
            raise InvalidDocumentException(
                [InvalidTemplateException(f"Value of '{path}' path must be a dictionary according to Swagger spec.")]
            )

        for path_item in self.get_conditional_contents(path_dict):  # type: ignore[no-untyped-call]
            path_item.setdefault(method, Py27Dict())

    def add_lambda_integration(  # type: ignore[no-untyped-def]
        self, path, method, integration_uri, method_auth_config=None, api_auth_config=None, condition=None
    ):
        """
        Adds aws_proxy APIGW integration to the given path+method.

        :param string path: Path name
        :param string method: HTTP Method
        :param string integration_uri: URI for the integration.
        """

        method = self._normalize_method_name(method)  # type: ignore[no-untyped-call]
        if self.has_integration(path, method):  # type: ignore[no-untyped-call]
            # Not throwing an error- we will add lambda integrations to existing swagger if not present
            return

        self.add_path(path, method)

        # Wrap the integration_uri in a Condition if one exists on that function
        # This is necessary so CFN doesn't try to resolve the integration reference.
        if condition:
            integration_uri = make_conditional(condition, integration_uri)

        for path_item in self.get_conditional_contents(self.paths.get(path)):  # type: ignore[no-untyped-call]
            # create as Py27Dict and insert key one by one to preserve input order
            if path_item[method] is None:
                path_item[method] = Py27Dict()
            path_item[method][self._X_APIGW_INTEGRATION] = Py27Dict()
            path_item[method][self._X_APIGW_INTEGRATION]["type"] = "aws_proxy"
            path_item[method][self._X_APIGW_INTEGRATION]["httpMethod"] = "POST"
            path_item[method][self._X_APIGW_INTEGRATION]["payloadFormatVersion"] = "2.0"
            path_item[method][self._X_APIGW_INTEGRATION]["uri"] = integration_uri

            if path == self._DEFAULT_PATH and method == self._X_ANY_METHOD:
                path_item[method]["isDefaultRoute"] = True

            # If 'responses' key is *not* present, add it with an empty dict as value
            path_item[method].setdefault("responses", Py27Dict())

            # If a condition is present, wrap all method contents up into the condition
            if condition:
                path_item[method] = make_conditional(condition, path_item[method])

    def make_path_conditional(self, path: str, condition: str) -> None:
        """
        Wrap entire API path definition in a CloudFormation if condition.
        :param path: path name
        :param condition: condition name
        """
        self.paths[path] = make_conditional(condition, self.paths[path])

    def iter_on_path(self) -> Iterator[str]:
        """
        Yields all the paths available in the Swagger. As a caller, if you add new paths to Swagger while iterating,
        they will not show up in this iterator

        :yields string: Path name
        """

        for path, _ in self.paths.items():
            yield path

    def iter_on_method_definitions_for_path_at_method(  # type: ignore[no-untyped-def]
        self, path_name, method_name, skip_methods_without_apigw_integration=True
    ):
        """
        Yields all the method definitions for the path+method combinations if path and/or method have IF conditionals.
        If there are no conditionals, will just yield the single method definition at the given path and method name.

        :param path_name: path name
        :param method_name: method name
        :param skip_methods_without_apigw_integration: if True, skips method definitions without apigw integration
        :yields dict: method definition
        """
        normalized_method_name = self._normalize_method_name(method_name)  # type: ignore[no-untyped-call]

        for path_item in self.get_conditional_contents(self.paths.get(path_name)):  # type: ignore[no-untyped-call]
            for method_definition in self.get_conditional_contents(path_item.get(normalized_method_name)):  # type: ignore[no-untyped-call]
                if skip_methods_without_apigw_integration and not self.method_definition_has_integration(method_definition):  # type: ignore[no-untyped-call]
                    continue
                yield method_definition

    def iter_on_all_methods_for_path(self, path_name, skip_methods_without_apigw_integration=True):  # type: ignore[no-untyped-def]
        """
        Yields all the (method name, method definition) tuples for the path, including those inside conditionals.

        :param path_name: path name
        :param skip_methods_without_apigw_integration: if True, skips method definitions without apigw integration
        :yields list of (method name, method definition) tuples
        """
        for path_item in self.get_conditional_contents(self.paths.get(path_name)):  # type: ignore[no-untyped-call]
            for method_name, method in path_item.items():
                for method_definition in self.get_conditional_contents(method):  # type: ignore[no-untyped-call]
                    if skip_methods_without_apigw_integration and not self.method_definition_has_integration(method_definition):  # type: ignore[no-untyped-call]
                        continue
                    normalized_method_name = self._normalize_method_name(method_name)  # type: ignore[no-untyped-call]
                    yield normalized_method_name, method_definition

    def add_timeout_to_method(self, api, path, method_name, timeout):  # type: ignore[no-untyped-def]
        """
        Adds a timeout to this path/method.

        :param dict api: Reference to the related Api's properties as defined in the template.
        :param string path: Path name
        :param string method_name: Method name
        :param int timeout: Timeout amount, in milliseconds
        """
        for method_definition in self.iter_on_method_definitions_for_path_at_method(path, method_name):  # type: ignore[no-untyped-call]
            method_definition[self._X_APIGW_INTEGRATION]["timeoutInMillis"] = timeout

    def add_path_parameters_to_method(self, api, path, method_name, path_parameters):  # type: ignore[no-untyped-def]
        """
        Adds path parameters to this path + method

        :param dict api: Reference to the related Api's properties as defined in the template.
        :param string path: Path name
        :param string method_name: Method name
        :param list path_parameters: list of strings of path parameters
        """
        for method_definition in self.iter_on_method_definitions_for_path_at_method(path, method_name):  # type: ignore[no-untyped-call]
            # create path parameter list
            # add it here if it doesn't exist, merge with existing otherwise.
            method_definition.setdefault("parameters", [])
            for param in path_parameters:
                # find an existing parameter with this name if it exists
                existing_parameter = next(
                    (
                        existing_parameter
                        for existing_parameter in method_definition.get("parameters", [])
                        if existing_parameter.get("name") == param
                    ),
                    None,
                )
                if existing_parameter:
                    # overwrite parameter values for existing path parameter
                    existing_parameter["in"] = "path"
                    existing_parameter["required"] = True
                else:
                    # create as Py27Dict and insert keys one by one to preserve input order
                    parameter = Py27Dict()
                    param = Py27UniStr(param) if isinstance(param, str) else param
                    parameter["name"] = param
                    parameter["in"] = "path"
                    parameter["required"] = True
                    method_definition.get("parameters").append(parameter)

    def add_payload_format_version_to_method(self, api, path, method_name, payload_format_version="2.0"):  # type: ignore[no-untyped-def]
        """
        Adds a payload format version to this path/method.

        :param dict api: Reference to the related Api's properties as defined in the template.
        :param string path: Path name
        :param string method_name: Method name
        :param string payload_format_version: payload format version sent to the integration
        """
        for method_definition in self.iter_on_method_definitions_for_path_at_method(path, method_name):  # type: ignore[no-untyped-call]
            method_definition[self._X_APIGW_INTEGRATION]["payloadFormatVersion"] = payload_format_version

    def add_authorizers_security_definitions(self, authorizers):  # type: ignore[no-untyped-def]
        """
        Add Authorizer definitions to the securityDefinitions part of Swagger.

        :param list authorizers: List of Authorizer configurations which get translated to securityDefinitions.
        """
        self.security_schemes = self.security_schemes or Py27Dict()

        for authorizer_name, authorizer in authorizers.items():
            self.security_schemes[authorizer_name] = authorizer.generate_openapi()

    def set_path_default_authorizer(self, path, default_authorizer, authorizers, api_authorizers):  # type: ignore[no-untyped-def]
        """
        Adds the default_authorizer to the security block for each method on this path unless an Authorizer
        was defined at the Function/Path/Method level. This is intended to be used to set the
        authorizer security restriction for all api methods based upon the default configured in the
        Serverless API.

        :param string path: Path name
        :param string default_authorizer: Name of the authorizer to use as the default. Must be a key in the
            authorizers param.
        :param list authorizers: List of Authorizer configurations defined on the related Api.
        """
        for path_item in self.get_conditional_contents(self.paths.get(path)):  # type: ignore[no-untyped-call]
            for method_name, method in path_item.items():
                normalized_method_name = self._normalize_method_name(method_name)  # type: ignore[no-untyped-call]
                # Excluding parameters section
                if normalized_method_name == "parameters":
                    continue
                if normalized_method_name != "options":
                    normalized_method_name = self._normalize_method_name(method_name)  # type: ignore[no-untyped-call]
                    # It is possible that the method could have two definitions in a Fn::If block.
                    if normalized_method_name not in path_item:
                        raise InvalidDocumentException(
                            [
                                InvalidTemplateException(
                                    f"Could not find {normalized_method_name} in {path} within DefinitionBody."
                                )
                            ]
                        )
                    for method_definition in self.get_conditional_contents(method):  # type: ignore[no-untyped-call]
                        # check if there is any method_definition given by customer
                        if not method_definition:
                            raise InvalidDocumentException(
                                [
                                    InvalidTemplateException(
                                        f"Invalid method definition ({normalized_method_name}) for path: {path}"
                                    )
                                ]
                            )
                        # If no integration given, then we don't need to process this definition (could be AWS::NoValue)
                        if not self.method_definition_has_integration(method_definition):  # type: ignore[no-untyped-call]
                            continue
                        existing_security = method_definition.get("security", [])
                        if existing_security:
                            continue
                        authorizer_list = []
                        if authorizers:
                            authorizer_list.extend(authorizers.keys())
                        security_dict = {}
                        security_dict[default_authorizer] = self._get_authorization_scopes(  # type: ignore[no-untyped-call]
                            api_authorizers, default_authorizer
                        )
                        authorizer_security = [security_dict]

                        security = authorizer_security

                        if security:
                            method_definition["security"] = security

    def add_auth_to_method(self, path, method_name, auth, api):  # type: ignore[no-untyped-def]
        """
        Adds auth settings for this path/method. Auth settings currently consist of Authorizers
        but this method will eventually include setting other auth settings such as Resource Policy, etc.
        This is used to configure the security for individual functions.

        :param string path: Path name
        :param string method_name: Method name
        :param dict auth: Auth configuration such as Authorizers
        :param dict api: Reference to the related Api's properties as defined in the template.
        """
        method_authorizer = auth and auth.get("Authorizer")
        authorization_scopes = auth.get("AuthorizationScopes", [])
        api_auth = api and api.get("Auth")
        authorizers = api_auth and api_auth.get("Authorizers")
        if method_authorizer:
            self._set_method_authorizer(path, method_name, method_authorizer, authorizers, authorization_scopes)  # type: ignore[no-untyped-call]

    def _set_method_authorizer(self, path, method_name, authorizer_name, authorizers, authorization_scopes=None):  # type: ignore[no-untyped-def]
        """
        Adds the authorizer_name to the security block for each method on this path.
        This is used to configure the authorizer for individual functions.

        :param string path: Path name
        :param string method_name: Method name
        :param string authorizer_name: Name of the authorizer to use. Must be a key in the
            authorizers param.
        :param list authorization_scopes: list of strings that are the auth scopes for this method
        """
        if authorization_scopes is None:
            authorization_scopes = []

        for method_definition in self.iter_on_method_definitions_for_path_at_method(path, method_name):  # type: ignore[no-untyped-call]
            existing_security = method_definition.get("security", [])

            security_dict = {}  # type: ignore[var-annotated]
            security_dict[authorizer_name] = []

            # Neither the NONE nor the AWS_IAM built-in authorizers support authorization scopes.
            if authorizer_name not in ["NONE", "AWS_IAM"]:
                method_authorization_scopes = authorizers[authorizer_name].get("AuthorizationScopes")
                if authorization_scopes:
                    method_authorization_scopes = authorization_scopes
                if authorizers[authorizer_name] and method_authorization_scopes:
                    security_dict[authorizer_name] = method_authorization_scopes

            authorizer_security = [security_dict]

            # This assumes there are no authorizers already configured in the existing security block
            security = existing_security + authorizer_security
            if security:
                method_definition["security"] = security

    def add_tags(self, tags):  # type: ignore[no-untyped-def]
        """
        Adds tags to the OpenApi definition using an ApiGateway extension for tag values.

        :param dict tags: dictionary of tagName:tagValue pairs.
        """
        for name, value in tags.items():
            # verify the tags definition is in the right format
            if not isinstance(self.tags, list):
                raise InvalidDocumentException(
                    [
                        InvalidTemplateException(
                            f"Tags in OpenApi DefinitionBody needs to be a list. {self.tags} is a {type(self.tags).__name__} not a list."
                        )
                    ]
                )
            # find an existing tag with this name if it exists
            existing_tag = next((existing_tag for existing_tag in self.tags if existing_tag.get("name") == name), None)
            if existing_tag:
                # overwrite tag value for an existing tag
                existing_tag[self._X_APIGW_TAG_VALUE] = value
            else:
                # create as Py27Dict and insert key one by one to preserve input order
                tag = Py27Dict()
                tag["name"] = name
                tag[self._X_APIGW_TAG_VALUE] = value
                self.tags.append(tag)

    def add_endpoint_config(self, disable_execute_api_endpoint):  # type: ignore[no-untyped-def]
        """Add endpoint configuration to _X_APIGW_ENDPOINT_CONFIG header in open api definition

        Following this guide:
        https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-swagger-extensions-endpoint-configuration.html
        https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-apigatewayv2-api.html#cfn-apigatewayv2-api-disableexecuteapiendpoint

        :param boolean disable_execute_api_endpoint: Specifies whether clients can invoke your API by using the default execute-api endpoint.

        """

        DISABLE_EXECUTE_API_ENDPOINT = "disableExecuteApiEndpoint"

        servers_configurations = self._doc.get(self._SERVERS, [Py27Dict()])
        for config in servers_configurations:
            endpoint_configuration = config.get(self._X_APIGW_ENDPOINT_CONFIG, {})
            endpoint_configuration[DISABLE_EXECUTE_API_ENDPOINT] = disable_execute_api_endpoint
            config[self._X_APIGW_ENDPOINT_CONFIG] = endpoint_configuration

        self._doc[self._SERVERS] = servers_configurations

    def add_cors(  # type: ignore[no-untyped-def]
        self,
        allow_origins,
        allow_headers=None,
        allow_methods=None,
        expose_headers=None,
        max_age=None,
        allow_credentials=None,
    ):
        """
        Add CORS configuration to this Api to _X_APIGW_CORS header in open api definition

        Following this guide:
        https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-cors.html
        https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-apigatewayv2-api-cors.html

        :param list/dict allowed_origins: Comma separate list of allowed origins.
            Value can also be an intrinsic function dict.
        :param list/dict allowed_headers: Comma separated list of allowed headers.
            Value can also be an intrinsic function dict.
        :param list/dict allowed_methods: Comma separated list of allowed methods.
            Value can also be an intrinsic function dict.
        :param list/dict expose_headers: Comma separated list of allowed methods.
            Value can also be an intrinsic function dict.
        :param integer/dict max_age: Maximum duration to cache the CORS Preflight request. Value is set on
            Access-Control-Max-Age header. Value can also be an intrinsic function dict.
        :param bool/None allowed_credentials: Flags whether request is allowed to contain credentials.
        """
        ALLOW_ORIGINS = "allowOrigins"
        ALLOW_HEADERS = "allowHeaders"
        ALLOW_METHODS = "allowMethods"
        EXPOSE_HEADERS = "exposeHeaders"
        MAX_AGE = "maxAge"
        ALLOW_CREDENTIALS = "allowCredentials"
        cors_headers = [ALLOW_ORIGINS, ALLOW_HEADERS, ALLOW_METHODS, EXPOSE_HEADERS, MAX_AGE, ALLOW_CREDENTIALS]
        cors_configuration = self._doc.get(self._X_APIGW_CORS, {})

        # intrinsics will not work if cors configuration is defined in open api and as a property to the HttpApi
        if allow_origins and is_intrinsic(allow_origins):
            cors_configuration_string = json.dumps(allow_origins)
            for header in cors_headers:
                # example: allowOrigins to AllowOrigins
                keyword = header[0].upper() + header[1:]
                cors_configuration_string = cors_configuration_string.replace(keyword, header)
            cors_configuration_dict = json.loads(cors_configuration_string)
            cors_configuration.update(cors_configuration_dict)

        else:
            if allow_origins:
                cors_configuration[ALLOW_ORIGINS] = allow_origins
            if allow_headers:
                cors_configuration[ALLOW_HEADERS] = allow_headers
            if allow_methods:
                cors_configuration[ALLOW_METHODS] = allow_methods
            if expose_headers:
                cors_configuration[EXPOSE_HEADERS] = expose_headers
            if max_age is not None:
                cors_configuration[MAX_AGE] = max_age
            if allow_credentials is True:
                cors_configuration[ALLOW_CREDENTIALS] = allow_credentials

        self._doc[self._X_APIGW_CORS] = cors_configuration

    def add_description(self, description):  # type: ignore[no-untyped-def]
        """Add description in open api definition, if it is not already defined

        :param string description: Description of the API
        """
        if self.info.get("description"):
            return
        self.info["description"] = description

    def has_api_gateway_cors(self):  # type: ignore[no-untyped-def]
        if self._doc.get(self._X_APIGW_CORS):
            return True
        return False

    @property
    def openapi(self):  # type: ignore[no-untyped-def]
        """
        Returns a **copy** of the OpenApi specification as a dictionary.

        :return dict: Dictionary containing the OpenApi specification
        """

        # Make sure any changes to the paths are reflected back in output
        self._doc["paths"] = self.paths

        if self.tags:
            self._doc["tags"] = self.tags

        if self.security_schemes:
            self._doc.setdefault("components", Py27Dict())
            self._doc["components"]["securitySchemes"] = self.security_schemes

        if self.info:
            self._doc["info"] = self.info

        return copy.deepcopy(self._doc)

    @staticmethod
    def is_valid(data: Any) -> bool:
        """
        Checks if the input data is a OpenApi document

        :param dict data: Data to be validated
        :return: True, if data is valid OpenApi
        """

        if bool(data) and isinstance(data, dict) and isinstance(data.get("paths"), dict):
            if bool(data.get("openapi")):
                return OpenApiEditor.safe_compare_regex_with_string(
                    OpenApiEditor.get_openapi_version_3_regex(), data["openapi"]
                )
        return False

    @staticmethod
    def gen_skeleton() -> Py27Dict:
        """
        Method to make an empty swagger file, with just some basic structure. Just enough to pass validator.

        :return dict: Dictionary of a skeleton swagger document
        """
        # create as Py27Dict and insert key one by one to preserve input order
        skeleton = Py27Dict()
        skeleton["openapi"] = "3.0.1"
        skeleton["info"] = Py27Dict()
        skeleton["info"]["version"] = "1.0"
        skeleton["info"]["title"] = ref("AWS::StackName")
        skeleton["paths"] = Py27Dict()
        return skeleton

    @staticmethod
    def _get_authorization_scopes(authorizers, default_authorizer):  # type: ignore[no-untyped-def]
        """
        Returns auth scopes for an authorizer if present
        :param authorizers: authorizer definitions
        :param default_authorizer: name of the default authorizer
        """
        if authorizers is not None:
            if (
                authorizers[default_authorizer]
                and authorizers[default_authorizer].get("AuthorizationScopes") is not None
            ):
                return authorizers[default_authorizer].get("AuthorizationScopes")
        return []

    @staticmethod
    def _normalize_method_name(method):  # type: ignore[no-untyped-def]
        """
        Returns a lower case, normalized version of HTTP Method. It also know how to handle API Gateway specific methods
        like "ANY"

        NOTE: Always normalize before using the `method` value passed in as input

        :param string method: Name of the HTTP Method
        :return string: Normalized method name
        """
        if not method or not isinstance(method, str):
            return method

        method = method.lower()
        if method == "any":
            return OpenApiEditor._X_ANY_METHOD
        return method

    @staticmethod
    def get_openapi_version_3_regex() -> str:
        openapi_version_3_regex = r"\A3(\.\d)(\.\d)?$"
        return openapi_version_3_regex

    @staticmethod
    def safe_compare_regex_with_string(regex: str, data: Any) -> bool:
        return re.match(regex, str(data)) is not None

    @staticmethod
    def get_path_without_trailing_slash(path):  # type: ignore[no-untyped-def]
        sub = re.sub(r"{([a-zA-Z0-9._-]+|proxy\+)}", "*", path)
        if isinstance(path, Py27UniStr):
            return Py27UniStr(sub)
        return sub
