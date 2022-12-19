import json
from re import match
from typing import Any, Dict, List, Optional

from samtranslator.model import PropertyType, Resource
from samtranslator.model.exceptions import InvalidResourceException
from samtranslator.model.intrinsics import fnSub, ref
from samtranslator.model.types import IS_DICT, IS_STR, is_type, list_of, one_of
from samtranslator.schema.common import PassThrough
from samtranslator.translator import logical_id_generator
from samtranslator.translator.arn_generator import ArnGenerator
from samtranslator.utils.py27hash_fix import Py27Dict, Py27UniStr
from samtranslator.validator.value_validator import sam_expect


class ApiGatewayRestApi(Resource):
    resource_type = "AWS::ApiGateway::RestApi"
    property_types = {
        "Body": PropertyType(False, IS_DICT),
        "BodyS3Location": PropertyType(False, IS_DICT),
        "CloneFrom": PropertyType(False, IS_STR),
        "Description": PropertyType(False, IS_STR),
        "FailOnWarnings": PropertyType(False, is_type(bool)),
        "Name": PropertyType(False, IS_STR),
        "Parameters": PropertyType(False, IS_DICT),
        "EndpointConfiguration": PropertyType(False, IS_DICT),
        "BinaryMediaTypes": PropertyType(False, is_type(list)),
        "MinimumCompressionSize": PropertyType(False, is_type(int)),
        "Mode": PropertyType(False, IS_STR),
        "ApiKeySourceType": PropertyType(False, IS_STR),
    }

    Body: Optional[Dict[str, Any]]
    BodyS3Location: Optional[Dict[str, Any]]
    CloneFrom: Optional[PassThrough]
    Description: Optional[PassThrough]
    FailOnWarnings: Optional[PassThrough]
    Name: Optional[PassThrough]
    Parameters: Optional[Dict[str, Any]]
    EndpointConfiguration: Optional[Dict[str, Any]]
    BinaryMediaTypes: Optional[List[Any]]
    MinimumCompressionSize: Optional[PassThrough]
    Mode: Optional[PassThrough]
    ApiKeySourceType: Optional[PassThrough]

    runtime_attrs = {"rest_api_id": lambda self: ref(self.logical_id)}


class ApiGatewayStage(Resource):
    resource_type = "AWS::ApiGateway::Stage"
    property_types = {
        "AccessLogSetting": PropertyType(False, IS_DICT),
        "CacheClusterEnabled": PropertyType(False, is_type(bool)),
        "CacheClusterSize": PropertyType(False, IS_STR),
        "CanarySetting": PropertyType(False, IS_DICT),
        "ClientCertificateId": PropertyType(False, IS_STR),
        "DeploymentId": PropertyType(True, IS_STR),
        "Description": PropertyType(False, IS_STR),
        "RestApiId": PropertyType(True, IS_STR),
        "StageName": PropertyType(True, one_of(IS_STR, IS_DICT)),
        "Tags": PropertyType(False, list_of(IS_DICT)),
        "TracingEnabled": PropertyType(False, is_type(bool)),
        "Variables": PropertyType(False, IS_DICT),
        "MethodSettings": PropertyType(False, is_type(list)),
    }

    runtime_attrs = {"stage_name": lambda self: ref(self.logical_id)}

    def update_deployment_ref(self, deployment_logical_id):  # type: ignore[no-untyped-def]
        self.DeploymentId = ref(deployment_logical_id)


class ApiGatewayAccount(Resource):
    resource_type = "AWS::ApiGateway::Account"
    property_types = {"CloudWatchRoleArn": PropertyType(False, one_of(IS_STR, IS_DICT))}


class ApiGatewayDeployment(Resource):
    _X_HASH_DELIMITER = "||"

    resource_type = "AWS::ApiGateway::Deployment"
    property_types = {
        "Description": PropertyType(False, IS_STR),
        "RestApiId": PropertyType(True, IS_STR),
        "StageDescription": PropertyType(False, IS_DICT),
        "StageName": PropertyType(False, IS_STR),
    }

    runtime_attrs = {"deployment_id": lambda self: ref(self.logical_id)}

    def make_auto_deployable(  # type: ignore[no-untyped-def]
        self, stage, openapi_version=None, swagger=None, domain=None, redeploy_restapi_parameters=None
    ):
        """
        Sets up the resource such that it will trigger a re-deployment when Swagger changes
        or the openapi version changes or a domain resource changes.

        :param swagger: Dictionary containing the Swagger definition of the API
        :param openapi_version: string containing value of OpenApiVersion flag in the template
        :param domain: Dictionary containing the custom domain configuration for the API
        :param redeploy_restapi_parameters: Dictionary containing the properties for which rest api will be redeployed
        """
        if not swagger:
            return

        # CloudFormation does NOT redeploy the API unless it has a new deployment resource
        # that points to latest RestApi resource. Append a hash of Swagger Body location to
        # redeploy only when the API data changes. First 10 characters of hash is good enough
        # to prevent redeployment when API has not changed

        # NOTE: `str(swagger)` is for backwards compatibility. Changing it to a JSON or something will break compat
        hash_input = [str(swagger)]
        if openapi_version:
            hash_input.append(str(openapi_version))
        if domain:
            hash_input.append(json.dumps(domain))
        if redeploy_restapi_parameters:
            function_names = redeploy_restapi_parameters.get("function_names")
        else:
            function_names = None
        # The deployment logical id is <api logicalId> + "Deployment"
        # The keyword "Deployment" is removed and all the function names associated with api is obtained
        if function_names and function_names.get(self.logical_id[:-10], None):
            hash_input.append(function_names.get(self.logical_id[:-10], ""))
        data = self._X_HASH_DELIMITER.join(hash_input)
        generator = logical_id_generator.LogicalIdGenerator(self.logical_id, data)
        self.logical_id = generator.gen()
        digest = generator.get_hash(length=40)  # type: ignore[no-untyped-call] # Get the full hash
        self.Description = "RestApi deployment id: {}".format(digest)
        stage.update_deployment_ref(self.logical_id)


class ApiGatewayResponse(object):
    ResponseParameterProperties = ["Headers", "Paths", "QueryStrings"]

    def __init__(
        self,
        api_logical_id: str,
        response_parameters: Optional[Dict[str, Any]] = None,
        response_templates: Optional[PassThrough] = None,
        status_code: Optional[str] = None,
    ) -> None:
        if response_parameters:
            # response_parameters has been validated in ApiGenerator._add_gateway_responses()
            for response_parameter_key in response_parameters.keys():
                if response_parameter_key not in ApiGatewayResponse.ResponseParameterProperties:
                    raise InvalidResourceException(
                        api_logical_id, "Invalid gateway response parameter '{}'".format(response_parameter_key)
                    )

        status_code_str = self._status_code_string(status_code)  # type: ignore[no-untyped-call]
        # status_code must look like a status code, if present. Let's not be judgmental; just check 0-999.
        if status_code and not match(r"^[0-9]{1,3}$", status_code_str):
            raise InvalidResourceException(api_logical_id, "Property 'StatusCode' must be numeric")

        self.api_logical_id = api_logical_id
        # Defaults to Py27Dict() as these will go into swagger
        self.response_parameters = response_parameters or Py27Dict()
        self.response_templates = response_templates or Py27Dict()
        self.status_code = status_code_str

    def generate_swagger(self):  # type: ignore[no-untyped-def]
        # Applying Py27Dict here as this goes into swagger
        swagger = Py27Dict()
        swagger["responseParameters"] = self._add_prefixes(self.response_parameters)  # type: ignore[no-untyped-call]
        swagger["responseTemplates"] = self.response_templates

        # Prevent "null" being written.
        if self.status_code:
            swagger["statusCode"] = self.status_code

        return swagger

    def _add_prefixes(self, response_parameters):  # type: ignore[no-untyped-def]
        GATEWAY_RESPONSE_PREFIX = "gatewayresponse."
        # applying Py27Dict as this is part of swagger
        prefixed_parameters = Py27Dict()

        parameter_prefix_pairs = [("Headers", "header."), ("Paths", "path."), ("QueryStrings", "querystring.")]
        for parameter_property_name, prefix in parameter_prefix_pairs:
            parameter_property_value = response_parameters.get(parameter_property_name, {})
            sam_expect(
                parameter_property_value, self.api_logical_id, f"ResponseParameters.{parameter_property_name}"
            ).to_be_a_map()
            for key, value in parameter_property_value.items():
                param_key = GATEWAY_RESPONSE_PREFIX + prefix + key
                if isinstance(key, Py27UniStr):
                    # if key is from template, we need to convert param_key to Py27UniStr
                    param_key = Py27UniStr(param_key)
                prefixed_parameters[param_key] = value

        return prefixed_parameters

    def _status_code_string(self, status_code):  # type: ignore[no-untyped-def]
        return None if status_code is None else str(status_code)


class ApiGatewayDomainName(Resource):
    resource_type = "AWS::ApiGateway::DomainName"
    property_types = {
        "RegionalCertificateArn": PropertyType(False, IS_STR),
        "DomainName": PropertyType(True, IS_STR),
        "EndpointConfiguration": PropertyType(False, IS_DICT),
        "MutualTlsAuthentication": PropertyType(False, IS_DICT),
        "SecurityPolicy": PropertyType(False, IS_STR),
        "CertificateArn": PropertyType(False, IS_STR),
        "OwnershipVerificationCertificateArn": PropertyType(False, IS_STR),
    }


class ApiGatewayBasePathMapping(Resource):
    resource_type = "AWS::ApiGateway::BasePathMapping"
    property_types = {
        "BasePath": PropertyType(False, IS_STR),
        "DomainName": PropertyType(True, IS_STR),
        "RestApiId": PropertyType(False, IS_STR),
        "Stage": PropertyType(False, IS_STR),
    }


class ApiGatewayUsagePlan(Resource):
    resource_type = "AWS::ApiGateway::UsagePlan"
    property_types = {
        "ApiStages": PropertyType(False, is_type(list)),
        "Description": PropertyType(False, IS_STR),
        "Quota": PropertyType(False, IS_DICT),
        "Tags": PropertyType(False, list_of(dict)),
        "Throttle": PropertyType(False, IS_DICT),
        "UsagePlanName": PropertyType(False, IS_STR),
    }
    runtime_attrs = {"usage_plan_id": lambda self: ref(self.logical_id)}


class ApiGatewayUsagePlanKey(Resource):
    resource_type = "AWS::ApiGateway::UsagePlanKey"
    property_types = {
        "KeyId": PropertyType(True, IS_STR),
        "KeyType": PropertyType(True, IS_STR),
        "UsagePlanId": PropertyType(True, IS_STR),
    }


class ApiGatewayApiKey(Resource):
    resource_type = "AWS::ApiGateway::ApiKey"
    property_types = {
        "CustomerId": PropertyType(False, IS_STR),
        "Description": PropertyType(False, IS_STR),
        "Enabled": PropertyType(False, is_type(bool)),
        "GenerateDistinctId": PropertyType(False, is_type(bool)),
        "Name": PropertyType(False, IS_STR),
        "StageKeys": PropertyType(False, is_type(list)),
        "Value": PropertyType(False, IS_STR),
    }

    runtime_attrs = {"api_key_id": lambda self: ref(self.logical_id)}


class ApiGatewayAuthorizer(object):
    _VALID_FUNCTION_PAYLOAD_TYPES = [None, "TOKEN", "REQUEST"]

    def __init__(  # type: ignore[no-untyped-def]
        self,
        api_logical_id=None,
        name=None,
        user_pool_arn=None,
        function_arn=None,
        identity=None,
        function_payload_type=None,
        function_invoke_role=None,
        is_aws_iam_authorizer=False,
        authorization_scopes=None,
    ):
        if authorization_scopes is None:
            authorization_scopes = []

        self.api_logical_id = api_logical_id
        self.name = name
        self.user_pool_arn = user_pool_arn
        self.function_arn = function_arn
        self.identity = identity
        self.function_payload_type = function_payload_type
        self.function_invoke_role = function_invoke_role
        self.is_aws_iam_authorizer = is_aws_iam_authorizer
        self.authorization_scopes = authorization_scopes

        if function_payload_type not in ApiGatewayAuthorizer._VALID_FUNCTION_PAYLOAD_TYPES:
            raise InvalidResourceException(
                api_logical_id,
                f"{name} Authorizer has invalid 'FunctionPayloadType': {function_payload_type}.",
            )

        if function_payload_type == "REQUEST" and self._is_missing_identity_source(identity):
            raise InvalidResourceException(
                api_logical_id,
                f"{name} Authorizer must specify Identity with at least one "
                "of Headers, QueryStrings, StageVariables, or Context.",
            )

        if authorization_scopes is not None and not isinstance(authorization_scopes, list):
            raise InvalidResourceException(api_logical_id, "AuthorizationScopes must be a list.")

    def _is_missing_identity_source(self, identity: Dict[str, Any]) -> bool:
        if not identity:
            return True

        sam_expect(identity, self.api_logical_id, f"Authorizer.{self.name}.Identity").to_be_a_map()

        headers = identity.get("Headers")
        query_strings = identity.get("QueryStrings")
        stage_variables = identity.get("StageVariables")
        context = identity.get("Context")
        ttl = identity.get("ReauthorizeEvery")

        required_properties_missing = not headers and not query_strings and not stage_variables and not context

        if ttl is None:
            return required_properties_missing
        try:
            ttl_int = int(ttl)
        # this will catch if and not convertable to an int
        except (TypeError, ValueError):
            # previous behavior before trying to read ttl
            return required_properties_missing

        # If we can resolve ttl, attempt to see if things are valid
        return ttl_int > 0 and required_properties_missing

    def generate_swagger(self):  # type: ignore[no-untyped-def]
        authorizer_type = self._get_type()  # type: ignore[no-untyped-call]
        APIGATEWAY_AUTHORIZER_KEY = "x-amazon-apigateway-authorizer"
        swagger = Py27Dict()
        swagger["type"] = "apiKey"
        swagger["name"] = self._get_swagger_header_name()  # type: ignore[no-untyped-call]
        swagger["in"] = "header"
        swagger["x-amazon-apigateway-authtype"] = self._get_swagger_authtype()  # type: ignore[no-untyped-call]

        if authorizer_type == "COGNITO_USER_POOLS":
            authorizer_dict = Py27Dict()
            authorizer_dict["type"] = self._get_swagger_authorizer_type()  # type: ignore[no-untyped-call]
            authorizer_dict["providerARNs"] = self._get_user_pool_arn_array()  # type: ignore[no-untyped-call]
            swagger[APIGATEWAY_AUTHORIZER_KEY] = authorizer_dict

        elif authorizer_type == "LAMBDA":
            swagger[APIGATEWAY_AUTHORIZER_KEY] = Py27Dict({"type": self._get_swagger_authorizer_type()})  # type: ignore[no-untyped-call, no-untyped-call]
            partition = ArnGenerator.get_partition_name()
            resource = "lambda:path/2015-03-31/functions/${__FunctionArn__}/invocations"
            authorizer_uri = fnSub(
                ArnGenerator.generate_arn(  # type: ignore[no-untyped-call]
                    partition=partition, service="apigateway", resource=resource, include_account_id=False
                ),
                {"__FunctionArn__": self.function_arn},
            )

            swagger[APIGATEWAY_AUTHORIZER_KEY]["authorizerUri"] = authorizer_uri
            reauthorize_every = self._get_reauthorize_every()  # type: ignore[no-untyped-call]
            function_invoke_role = self._get_function_invoke_role()  # type: ignore[no-untyped-call]

            if reauthorize_every is not None:
                swagger[APIGATEWAY_AUTHORIZER_KEY]["authorizerResultTtlInSeconds"] = reauthorize_every

            if function_invoke_role:
                swagger[APIGATEWAY_AUTHORIZER_KEY]["authorizerCredentials"] = function_invoke_role

            if self._get_function_payload_type() == "REQUEST":  # type: ignore[no-untyped-call]
                identity_source = self._get_identity_source()
                if identity_source:
                    swagger[APIGATEWAY_AUTHORIZER_KEY]["identitySource"] = self._get_identity_source()

        # Authorizer Validation Expression is only allowed on COGNITO_USER_POOLS and LAMBDA_TOKEN
        is_lambda_token_authorizer = authorizer_type == "LAMBDA" and self._get_function_payload_type() == "TOKEN"  # type: ignore[no-untyped-call]

        if authorizer_type == "COGNITO_USER_POOLS" or is_lambda_token_authorizer:
            identity_validation_expression = self._get_identity_validation_expression()  # type: ignore[no-untyped-call]

            if identity_validation_expression:
                swagger[APIGATEWAY_AUTHORIZER_KEY]["identityValidationExpression"] = identity_validation_expression

        return swagger

    def _get_identity_validation_expression(self):  # type: ignore[no-untyped-def]
        return self.identity and self.identity.get("ValidationExpression")

    @staticmethod
    def _build_identity_source_item(item_prefix: str, prop_value: str) -> str:
        item = item_prefix + prop_value
        if isinstance(prop_value, Py27UniStr):
            item = Py27UniStr(item)
        return item

    def _build_identity_source_item_array(self, prop_key: str, item_prefix: str) -> List[str]:
        arr: List[str] = []
        prop_value_list = self.identity.get(prop_key)
        if prop_value_list:
            prop_path = f"Auth.Authorizers.{self.name}.Identity.{prop_key}"
            sam_expect(prop_value_list, self.api_logical_id, prop_path).to_be_a_list()
            for index, prop_value in enumerate(prop_value_list):
                sam_expect(prop_value, self.api_logical_id, f"{prop_path}[{index}]").to_be_a_string()
                arr.append(self._build_identity_source_item(item_prefix, prop_value))
        return arr

    def _get_identity_source(self) -> str:
        key_prefix_pairs = [
            ("Headers", "method.request.header."),
            ("QueryStrings", "method.request.querystring."),
            ("StageVariables", "stageVariables."),
            ("Context", "context."),
        ]

        identity_source_array = []
        for prop_key, item_prefix in key_prefix_pairs:
            identity_source_array.extend(self._build_identity_source_item_array(prop_key, item_prefix))

        identity_source = ", ".join(identity_source_array)
        if any(isinstance(i, Py27UniStr) for i in identity_source_array):
            # Convert identity_source to Py27UniStr if any part of it is Py27UniStr
            identity_source = Py27UniStr(identity_source)

        return identity_source

    def _get_user_pool_arn_array(self):  # type: ignore[no-untyped-def]
        return self.user_pool_arn if isinstance(self.user_pool_arn, list) else [self.user_pool_arn]

    def _get_swagger_header_name(self):  # type: ignore[no-untyped-def]
        authorizer_type = self._get_type()  # type: ignore[no-untyped-call]
        payload_type = self._get_function_payload_type()  # type: ignore[no-untyped-call]

        if authorizer_type == "LAMBDA" and payload_type == "REQUEST":
            return "Unused"

        return self._get_identity_header()  # type: ignore[no-untyped-call]

    def _get_type(self):  # type: ignore[no-untyped-def]
        if self.is_aws_iam_authorizer:
            return "AWS_IAM"

        if self.user_pool_arn:
            return "COGNITO_USER_POOLS"

        return "LAMBDA"

    def _get_identity_header(self):  # type: ignore[no-untyped-def]
        if self.identity and not isinstance(self.identity, dict):
            raise InvalidResourceException(
                self.api_logical_id,
                "Auth.Authorizers.<Authorizer>.Identity must be a dict (LambdaTokenAuthorizationIdentity, "
                "LambdaRequestAuthorizationIdentity or CognitoAuthorizationIdentity).",
            )

        if not self.identity or not self.identity.get("Header"):
            return "Authorization"

        return self.identity.get("Header")

    def _get_reauthorize_every(self):  # type: ignore[no-untyped-def]
        if not self.identity:
            return None

        return self.identity.get("ReauthorizeEvery")

    def _get_function_invoke_role(self):  # type: ignore[no-untyped-def]
        if not self.function_invoke_role or self.function_invoke_role == "NONE":
            return None

        return self.function_invoke_role

    def _get_swagger_authtype(self):  # type: ignore[no-untyped-def]
        authorizer_type = self._get_type()  # type: ignore[no-untyped-call]
        if authorizer_type == "AWS_IAM":
            return "awsSigv4"

        if authorizer_type == "COGNITO_USER_POOLS":
            return "cognito_user_pools"

        return "custom"

    def _get_function_payload_type(self):  # type: ignore[no-untyped-def]
        return "TOKEN" if not self.function_payload_type else self.function_payload_type

    def _get_swagger_authorizer_type(self):  # type: ignore[no-untyped-def]
        authorizer_type = self._get_type()  # type: ignore[no-untyped-call]

        if authorizer_type == "COGNITO_USER_POOLS":
            return "cognito_user_pools"

        payload_type = self._get_function_payload_type()  # type: ignore[no-untyped-call]

        if payload_type == "REQUEST":
            return "request"

        if payload_type == "TOKEN":
            return "token"
