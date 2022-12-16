from typing import Any, Dict, List, Optional, Union

from samtranslator.model import PropertyType, Resource
from samtranslator.model.types import IS_DICT, is_type, one_of, IS_STR, list_of
from samtranslator.model.intrinsics import ref, fnSub
from samtranslator.model.exceptions import ExpectedType, InvalidResourceException
from samtranslator.translator.arn_generator import ArnGenerator
from samtranslator.utils.types import Intrinsicable
from samtranslator.validator.value_validator import sam_expect

APIGATEWAY_AUTHORIZER_KEY = "x-amazon-apigateway-authorizer"


class ApiGatewayV2HttpApi(Resource):
    resource_type = "AWS::ApiGatewayV2::Api"
    property_types = {
        "Body": PropertyType(False, IS_DICT),
        "BodyS3Location": PropertyType(False, IS_DICT),
        "Description": PropertyType(False, IS_STR),
        "FailOnWarnings": PropertyType(False, is_type(bool)),
        "DisableExecuteApiEndpoint": PropertyType(False, is_type(bool)),
        "BasePath": PropertyType(False, IS_STR),
        "CorsConfiguration": PropertyType(False, IS_DICT),
    }

    runtime_attrs = {"http_api_id": lambda self: ref(self.logical_id)}


class ApiGatewayV2Stage(Resource):
    resource_type = "AWS::ApiGatewayV2::Stage"
    property_types = {
        "AccessLogSettings": PropertyType(False, IS_DICT),
        "DefaultRouteSettings": PropertyType(False, IS_DICT),
        "RouteSettings": PropertyType(False, IS_DICT),
        "ClientCertificateId": PropertyType(False, IS_STR),
        "Description": PropertyType(False, IS_STR),
        "ApiId": PropertyType(True, IS_STR),
        "StageName": PropertyType(False, one_of(IS_STR, IS_DICT)),
        "Tags": PropertyType(False, IS_DICT),
        "StageVariables": PropertyType(False, IS_DICT),
        "AutoDeploy": PropertyType(False, is_type(bool)),
    }

    runtime_attrs = {"stage_name": lambda self: ref(self.logical_id)}


class ApiGatewayV2DomainName(Resource):
    resource_type = "AWS::ApiGatewayV2::DomainName"
    property_types = {
        "DomainName": PropertyType(True, IS_STR),
        "DomainNameConfigurations": PropertyType(False, list_of(IS_DICT)),
        "MutualTlsAuthentication": PropertyType(False, IS_DICT),
        "Tags": PropertyType(False, IS_DICT),
    }

    DomainName: Intrinsicable[str]
    DomainNameConfigurations: Optional[List[Dict[str, Any]]]
    MutualTlsAuthentication: Optional[Dict[str, Any]]
    Tags: Optional[Dict[str, Any]]


class ApiGatewayV2ApiMapping(Resource):
    resource_type = "AWS::ApiGatewayV2::ApiMapping"
    property_types = {
        "ApiId": PropertyType(True, IS_STR),
        "ApiMappingKey": PropertyType(False, IS_STR),
        "DomainName": PropertyType(True, IS_STR),
        "Stage": PropertyType(True, IS_STR),
    }


# https://docs.aws.amazon.com/apigatewayv2/latest/api-reference/apis-apiid-authorizers-authorizerid.html#apis-apiid-authorizers-authorizerid-model-jwtconfiguration
# Change to TypedDict when we don't have to support Python 3.7
JwtConfiguration = Dict[str, Union[str, List[str]]]


class ApiGatewayV2Authorizer(object):
    def __init__(  # type: ignore[no-untyped-def]
        self,
        api_logical_id=None,
        name=None,
        authorization_scopes=None,
        jwt_configuration=None,
        id_source=None,
        function_arn=None,
        function_invoke_role=None,
        identity=None,
        authorizer_payload_format_version=None,
        enable_simple_responses=None,
        is_aws_iam_authorizer=False,
    ):
        """
        Creates an authorizer for use in V2 Http Apis
        """
        self.api_logical_id = api_logical_id
        self.name = name
        self.authorization_scopes = authorization_scopes
        self.jwt_configuration: Optional[JwtConfiguration] = self._get_jwt_configuration(jwt_configuration)
        self.id_source = id_source
        self.function_arn = function_arn
        self.function_invoke_role = function_invoke_role
        self.identity = identity
        self.authorizer_payload_format_version = authorizer_payload_format_version
        self.enable_simple_responses = enable_simple_responses
        self.is_aws_iam_authorizer = is_aws_iam_authorizer

        self._validate_input_parameters()  # type: ignore[no-untyped-call]

        authorizer_type = self._get_auth_type()  # type: ignore[no-untyped-call]

        # Validate necessary parameters exist
        if authorizer_type == "JWT":
            self._validate_jwt_authorizer()

        if authorizer_type == "REQUEST":
            self._validate_lambda_authorizer()  # type: ignore[no-untyped-call]

    def _get_auth_type(self):  # type: ignore[no-untyped-def]
        if self.is_aws_iam_authorizer:
            return "AWS_IAM"
        if self.jwt_configuration:
            return "JWT"
        return "REQUEST"

    def _validate_input_parameters(self):  # type: ignore[no-untyped-def]
        authorizer_type = self._get_auth_type()  # type: ignore[no-untyped-call]

        if self.authorization_scopes is not None and not isinstance(self.authorization_scopes, list):
            raise InvalidResourceException(self.api_logical_id, "AuthorizationScopes must be a list.")

        if self.authorization_scopes is not None and not authorizer_type == "JWT":
            raise InvalidResourceException(
                self.api_logical_id, "AuthorizationScopes must be defined only for OAuth2 Authorizer."
            )

        if self.jwt_configuration is not None and not authorizer_type == "JWT":
            raise InvalidResourceException(
                self.api_logical_id, "JwtConfiguration must be defined only for OAuth2 Authorizer."
            )

        if self.id_source is not None and not authorizer_type == "JWT":
            raise InvalidResourceException(
                self.api_logical_id, "IdentitySource must be defined only for OAuth2 Authorizer."
            )

        if self.function_arn is not None and not authorizer_type == "REQUEST":
            raise InvalidResourceException(
                self.api_logical_id, "FunctionArn must be defined only for Lambda Authorizer."
            )

        if self.function_invoke_role is not None and not authorizer_type == "REQUEST":
            raise InvalidResourceException(
                self.api_logical_id, "FunctionInvokeRole must be defined only for Lambda Authorizer."
            )

        if self.identity is not None and not authorizer_type == "REQUEST":
            raise InvalidResourceException(self.api_logical_id, "Identity must be defined only for Lambda Authorizer.")

        if self.authorizer_payload_format_version is not None and not authorizer_type == "REQUEST":
            raise InvalidResourceException(
                self.api_logical_id, "AuthorizerPayloadFormatVersion must be defined only for Lambda Authorizer."
            )

        if self.enable_simple_responses is not None and not authorizer_type == "REQUEST":
            raise InvalidResourceException(
                self.api_logical_id, "EnableSimpleResponses must be defined only for Lambda Authorizer."
            )

    def _validate_jwt_authorizer(self) -> None:
        if not self.jwt_configuration:
            raise InvalidResourceException(
                self.api_logical_id, f"{self.name} OAuth2 Authorizer must define 'JwtConfiguration'."
            )
        if not self.id_source:
            raise InvalidResourceException(
                self.api_logical_id, f"{self.name} OAuth2 Authorizer must define 'IdentitySource'."
            )

    def _validate_lambda_authorizer(self):  # type: ignore[no-untyped-def]
        if not self.function_arn:
            raise InvalidResourceException(
                self.api_logical_id, f"{self.name} Lambda Authorizer must define 'FunctionArn'."
            )
        if not self.authorizer_payload_format_version:
            raise InvalidResourceException(
                self.api_logical_id, f"{self.name} Lambda Authorizer must define 'AuthorizerPayloadFormatVersion'."
            )

    def generate_openapi(self) -> Dict[str, Any]:
        """
        Generates OAS for the securitySchemes section
        """
        authorizer_type = self._get_auth_type()  # type: ignore[no-untyped-call]
        openapi: Dict[str, Any]

        if authorizer_type == "AWS_IAM":
            openapi = {
                "type": "apiKey",
                "name": "Authorization",
                "in": "header",
                "x-amazon-apigateway-authtype": "awsSigv4",
            }

        elif authorizer_type == "JWT":
            openapi = {
                "type": "oauth2",
                APIGATEWAY_AUTHORIZER_KEY: {
                    "jwtConfiguration": self.jwt_configuration,
                    "identitySource": self.id_source,
                    "type": "jwt",
                },
            }

        elif authorizer_type == "REQUEST":
            openapi = {
                "type": "apiKey",
                "name": "Unused",
                "in": "header",
                APIGATEWAY_AUTHORIZER_KEY: {"type": "request"},
            }

            # Generate the lambda arn
            partition = ArnGenerator.get_partition_name()
            resource = "lambda:path/2015-03-31/functions/${__FunctionArn__}/invocations"
            authorizer_uri = fnSub(
                ArnGenerator.generate_arn(  # type: ignore[no-untyped-call]
                    partition=partition, service="apigateway", resource=resource, include_account_id=False
                ),
                {"__FunctionArn__": self.function_arn},
            )
            openapi[APIGATEWAY_AUTHORIZER_KEY]["authorizerUri"] = authorizer_uri

            # Set authorizerCredentials if present
            function_invoke_role = self._get_function_invoke_role()  # type: ignore[no-untyped-call]
            if function_invoke_role:
                openapi[APIGATEWAY_AUTHORIZER_KEY]["authorizerCredentials"] = function_invoke_role

            # Set identitySource if present
            if self.identity:
                sam_expect(self.identity, self.api_logical_id, f"Auth.Authorizers.{self.name}.Identity").to_be_a_map()
                # Set authorizerResultTtlInSeconds if present
                reauthorize_every = self.identity.get("ReauthorizeEvery")
                if reauthorize_every is not None:
                    openapi[APIGATEWAY_AUTHORIZER_KEY]["authorizerResultTtlInSeconds"] = reauthorize_every

                # Set identitySource if present
                openapi[APIGATEWAY_AUTHORIZER_KEY]["identitySource"] = self._get_identity_source(self.identity)

            # Set authorizerPayloadFormatVersion. It's a required parameter
            openapi[APIGATEWAY_AUTHORIZER_KEY][
                "authorizerPayloadFormatVersion"
            ] = self.authorizer_payload_format_version

            # Set enableSimpleResponses if present
            if self.enable_simple_responses:
                openapi[APIGATEWAY_AUTHORIZER_KEY]["enableSimpleResponses"] = self.enable_simple_responses

        else:
            raise ValueError(f"Unexpected authorizer_type: {authorizer_type}")
        return openapi

    def _get_function_invoke_role(self):  # type: ignore[no-untyped-def]
        if not self.function_invoke_role or self.function_invoke_role == "NONE":
            return None

        return self.function_invoke_role

    def _get_identity_source(self, auth_identity: Dict[str, Any]) -> List[str]:
        """
        Generate the list of identitySource using authorizer's Identity config by flatting them.
        For the format of identitySource, see:
        https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-swagger-extensions-authorizer.html

        It will add API GW prefix to each item:
        - prefix "$request.header." to all values in "Headers"
        - prefix "$request.querystring." to all values in "QueryStrings"
        - prefix "$stageVariables." to all values in "StageVariables"
        - prefix "$context." to all values in "Context"
        """
        identity_source: List[str] = []

        identity_property_path = f"Authorizers.{self.name}.Identity"

        for prefix, property_name in [
            ("$request.header.", "Headers"),
            ("$request.querystring.", "QueryStrings"),
            ("$stageVariables.", "StageVariables"),
            ("$context.", "Context"),
        ]:
            property_values = auth_identity.get(property_name)
            if property_values:
                sam_expect(
                    property_values, self.api_logical_id, f"{identity_property_path}.{property_name}"
                ).to_be_a_list_of(ExpectedType.STRING)
                identity_source += [prefix + value for value in property_values]

        return identity_source

    @staticmethod
    def _get_jwt_configuration(props: Optional[Dict[str, Union[str, List[str]]]]) -> Optional[JwtConfiguration]:
        """Make sure that JWT configuration dict keys are lower case.

        ApiGatewayV2Authorizer doesn't create `AWS::ApiGatewayV2::Authorizer` but generates
        Open Api which will be appended to the API's Open Api definition body.
        For Open Api JWT configuration keys should be in lower case.
        But for `AWS::ApiGatewayV2::Authorizer` the same keys are capitalized,
        the way it's usually done in CloudFormation resources.
        Users get often confused when passing capitalized key to `AWS::Serverless::HttpApi` doesn't work.
        There exist a comment about that in the documentation
        https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-property-httpapi-oauth2authorizer.html#sam-httpapi-oauth2authorizer-jwtconfiguration
        but the comment doesn't prevent users from making the error.

        Parameters
        ----------
        props
            jwt configuration dict with the keys either lower case or capitalized

        Returns
        -------
            jwt configuration dict with low case keys
        """
        if not props:
            return None
        return {k.lower(): v for k, v in props.items()}
