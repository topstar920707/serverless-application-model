import re
from collections import namedtuple

from samtranslator.metrics.method_decorator import cw_timer
from samtranslator.model.intrinsics import ref, fnGetAtt
from samtranslator.model.apigatewayv2 import (
    ApiGatewayV2HttpApi,
    ApiGatewayV2Stage,
    ApiGatewayV2Authorizer,
    ApiGatewayV2DomainName,
    ApiGatewayV2ApiMapping,
)
from samtranslator.model.exceptions import InvalidResourceException
from samtranslator.model.s3_utils.uri_parser import parse_s3_uri
from samtranslator.open_api.open_api import OpenApiEditor
from samtranslator.translator.logical_id_generator import LogicalIdGenerator
from samtranslator.model.intrinsics import is_intrinsic, is_intrinsic_no_value
from samtranslator.model.route53 import Route53RecordSetGroup

_CORS_WILDCARD = "*"
CorsProperties = namedtuple(
    "CorsProperties", ["AllowMethods", "AllowHeaders", "AllowOrigins", "MaxAge", "ExposeHeaders", "AllowCredentials"]
)
CorsProperties.__new__.__defaults__ = (None, None, None, None, None, False)

AuthProperties = namedtuple("AuthProperties", ["Authorizers", "DefaultAuthorizer", "EnableIamAuthorizer"])
AuthProperties.__new__.__defaults__ = (None, None, False)
DefaultStageName = "$default"
HttpApiTagName = "httpapi:createdBy"


class HttpApiGenerator(object):
    def __init__(  # type: ignore[no-untyped-def]
        self,
        logical_id,
        stage_variables,
        depends_on,
        definition_body,
        definition_uri,
        stage_name,
        tags=None,
        auth=None,
        cors_configuration=None,
        access_log_settings=None,
        route_settings=None,
        default_route_settings=None,
        resource_attributes=None,
        passthrough_resource_attributes=None,
        domain=None,
        fail_on_warnings=None,
        description=None,
        disable_execute_api_endpoint=None,
    ):
        """Constructs an API Generator class that generates API Gateway resources

        :param logical_id: Logical id of the SAM API Resource
        :param stage_variables: API Gateway Variables
        :param depends_on: Any resources that need to be depended on
        :param definition_body: API definition
        :param definition_uri: URI to API definition
        :param name: Name of the API Gateway resource
        :param stage_name: Name of the Stage
        :param tags: Stage and API Tags
        :param access_log_settings: Whether to send access logs and where for Stage
        :param resource_attributes: Resource attributes to add to API resources
        :param passthrough_resource_attributes: Attributes such as `Condition` that are added to derived resources
        :param description: Description of the API Gateway resource
        """
        self.logical_id = logical_id
        self.stage_variables = stage_variables
        self.depends_on = depends_on
        self.definition_body = definition_body
        self.definition_uri = definition_uri
        self.stage_name = stage_name
        if not self.stage_name:
            self.stage_name = DefaultStageName
        self.auth = auth
        self.cors_configuration = cors_configuration
        self.tags = tags
        self.access_log_settings = access_log_settings
        self.route_settings = route_settings
        self.default_route_settings = default_route_settings
        self.resource_attributes = resource_attributes
        self.passthrough_resource_attributes = passthrough_resource_attributes
        self.domain = domain
        self.fail_on_warnings = fail_on_warnings
        self.description = description
        self.disable_execute_api_endpoint = disable_execute_api_endpoint

    def _construct_http_api(self):  # type: ignore[no-untyped-def]
        """Constructs and returns the ApiGatewayV2 HttpApi.

        :returns: the HttpApi to which this SAM Api corresponds
        :rtype: model.apigatewayv2.ApiGatewayHttpApi
        """
        http_api = ApiGatewayV2HttpApi(self.logical_id, depends_on=self.depends_on, attributes=self.resource_attributes)

        if self.definition_uri and self.definition_body:
            raise InvalidResourceException(
                self.logical_id, "Specify either 'DefinitionUri' or 'DefinitionBody' property and not both."
            )
        if self.cors_configuration:
            # call this method to add cors in open api
            self._add_cors()  # type: ignore[no-untyped-call]

        self._add_auth()  # type: ignore[no-untyped-call]
        self._add_tags()  # type: ignore[no-untyped-call]

        if self.fail_on_warnings:
            http_api.FailOnWarnings = self.fail_on_warnings

        if self.disable_execute_api_endpoint is not None:
            self._add_endpoint_configuration()  # type: ignore[no-untyped-call]

        self._add_description()  # type: ignore[no-untyped-call]

        if self.definition_uri:
            http_api.BodyS3Location = self._construct_body_s3_dict()  # type: ignore[no-untyped-call]
        elif self.definition_body:
            http_api.Body = self.definition_body
        else:
            raise InvalidResourceException(
                self.logical_id,
                "'DefinitionUri' or 'DefinitionBody' are required properties of an "
                "'AWS::Serverless::HttpApi'. Add a value for one of these properties or "
                "add a 'HttpApi' event to an 'AWS::Serverless::Function'.",
            )

        return http_api

    def _add_endpoint_configuration(self):  # type: ignore[no-untyped-def]
        """Add disableExecuteApiEndpoint if it is set in SAM
        HttpApi doesn't have vpcEndpointIds

        Note:
        DisableExecuteApiEndpoint as a property of AWS::ApiGatewayV2::Api needs both DefinitionBody and
        DefinitionUri to be None. However, if neither DefinitionUri nor DefinitionBody are specified,
        SAM will generate a openapi definition body based on template configuration.
        https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-resource-api.html#sam-api-definitionbody
        For this reason, we always put DisableExecuteApiEndpoint into openapi object.

        """
        if self.disable_execute_api_endpoint is not None and not self.definition_body:
            raise InvalidResourceException(
                self.logical_id, "DisableExecuteApiEndpoint works only within 'DefinitionBody' property."
            )
        editor = OpenApiEditor(self.definition_body)  # type: ignore[no-untyped-call]

        # if DisableExecuteApiEndpoint is set in both definition_body and as a property,
        # SAM merges and overrides the disableExecuteApiEndpoint in definition_body with headers of
        # "x-amazon-apigateway-endpoint-configuration"
        editor.add_endpoint_config(self.disable_execute_api_endpoint)  # type: ignore[no-untyped-call]

        # Assign the OpenApi back to template
        self.definition_body = editor.openapi

    def _add_cors(self):  # type: ignore[no-untyped-def]
        """
        Add CORS configuration if CORSConfiguration property is set in SAM.
        Adds CORS configuration only if DefinitionBody is present and
        APIGW extension for CORS is not present in the DefinitionBody
        """

        if self.cors_configuration and not self.definition_body:
            raise InvalidResourceException(
                self.logical_id, "Cors works only with inline OpenApi specified in 'DefinitionBody' property."
            )

        # If cors configuration is set to true add * to the allow origins.
        # This also support referencing the value as a parameter
        if isinstance(self.cors_configuration, bool):
            # if cors config is true add Origins as "'*'"
            properties = CorsProperties(AllowOrigins=[_CORS_WILDCARD])  # type: ignore[call-arg]

        elif is_intrinsic(self.cors_configuration):
            # Just set Origin property. Intrinsics will be handledOthers will be defaults
            properties = CorsProperties(AllowOrigins=self.cors_configuration)  # type: ignore[call-arg]

        elif isinstance(self.cors_configuration, dict):
            # Make sure keys in the dict are recognized
            if not all(key in CorsProperties._fields for key in self.cors_configuration.keys()):
                raise InvalidResourceException(self.logical_id, "Invalid value for 'Cors' property.")

            properties = CorsProperties(**self.cors_configuration)

        else:
            raise InvalidResourceException(self.logical_id, "Invalid value for 'Cors' property.")

        if not OpenApiEditor.is_valid(self.definition_body):
            raise InvalidResourceException(
                self.logical_id,
                "Unable to add Cors configuration because "
                "'DefinitionBody' does not contain a valid "
                "OpenApi definition.",
            )

        if properties.AllowCredentials is True and properties.AllowOrigins == [_CORS_WILDCARD]:
            raise InvalidResourceException(
                self.logical_id,
                "Unable to add Cors configuration because "
                "'AllowCredentials' can not be true when "
                "'AllowOrigin' is \"'*'\" or not set.",
            )

        editor = OpenApiEditor(self.definition_body)  # type: ignore[no-untyped-call]
        # if CORS is set in both definition_body and as a CorsConfiguration property,
        # SAM merges and overrides the cors headers in definition_body with headers of CorsConfiguration
        editor.add_cors(  # type: ignore[no-untyped-call]
            properties.AllowOrigins,
            properties.AllowHeaders,
            properties.AllowMethods,
            properties.ExposeHeaders,
            properties.MaxAge,
            properties.AllowCredentials,
        )

        # Assign the OpenApi back to template
        self.definition_body = editor.openapi

    def _construct_api_domain(self, http_api, route53_record_set_groups):  # type: ignore[no-untyped-def]
        """
        Constructs and returns the ApiGateway Domain and BasepathMapping
        """
        if self.domain is None:
            return None, None, None

        if self.domain.get("DomainName") is None or self.domain.get("CertificateArn") is None:
            raise InvalidResourceException(
                self.logical_id, "Custom Domains only works if both DomainName and CertificateArn are provided."
            )

        self.domain["ApiDomainName"] = "{}{}".format(
            "ApiGatewayDomainNameV2", LogicalIdGenerator("", self.domain.get("DomainName")).gen()  # type: ignore[no-untyped-call, no-untyped-call]
        )

        domain = ApiGatewayV2DomainName(
            self.domain.get("ApiDomainName"), attributes=self.passthrough_resource_attributes
        )
        domain_config = {}
        domain.DomainName = self.domain.get("DomainName")
        domain.Tags = self.tags
        endpoint = self.domain.get("EndpointConfiguration")

        if endpoint is None:
            endpoint = "REGIONAL"
            # to make sure that default is always REGIONAL
            self.domain["EndpointConfiguration"] = "REGIONAL"
        elif endpoint not in ["REGIONAL"]:
            raise InvalidResourceException(
                self.logical_id,
                "EndpointConfiguration for Custom Domains must be one of {}.".format(["REGIONAL"]),
            )
        domain_config["EndpointType"] = endpoint

        if self.domain.get("OwnershipVerificationCertificateArn", None):
            domain_config["OwnershipVerificationCertificateArn"] = self.domain.get(
                "OwnershipVerificationCertificateArn"
            )

        domain_config["CertificateArn"] = self.domain.get("CertificateArn")
        if self.domain.get("SecurityPolicy", None):
            domain_config["SecurityPolicy"] = self.domain.get("SecurityPolicy")

        domain.DomainNameConfigurations = [domain_config]

        mutual_tls_auth = self.domain.get("MutualTlsAuthentication", None)
        if mutual_tls_auth:
            if isinstance(mutual_tls_auth, dict):
                if not set(mutual_tls_auth.keys()).issubset({"TruststoreUri", "TruststoreVersion"}):
                    invalid_keys = []
                    for key in mutual_tls_auth.keys():
                        if key not in {"TruststoreUri", "TruststoreVersion"}:
                            invalid_keys.append(key)
                    invalid_keys.sort()
                    raise InvalidResourceException(
                        ",".join(invalid_keys),
                        "Available MutualTlsAuthentication fields are {}.".format(
                            ["TruststoreUri", "TruststoreVersion"]
                        ),
                    )
                domain.MutualTlsAuthentication = {}
                if mutual_tls_auth.get("TruststoreUri", None):
                    domain.MutualTlsAuthentication["TruststoreUri"] = mutual_tls_auth["TruststoreUri"]  # type: ignore[attr-defined]
                if mutual_tls_auth.get("TruststoreVersion", None):
                    domain.MutualTlsAuthentication["TruststoreVersion"] = mutual_tls_auth["TruststoreVersion"]  # type: ignore[attr-defined]
            else:
                raise InvalidResourceException(
                    mutual_tls_auth,
                    "MutualTlsAuthentication must be a map with at least one of the following fields {}.".format(
                        ["TruststoreUri", "TruststoreVersion"]
                    ),
                )

        # Create BasepathMappings
        if self.domain.get("BasePath") and isinstance(self.domain.get("BasePath"), str):
            basepaths = [self.domain.get("BasePath")]
        elif self.domain.get("BasePath") and isinstance(self.domain.get("BasePath"), list):
            basepaths = self.domain.get("BasePath")
        else:
            basepaths = None
        basepath_resource_list = self._construct_basepath_mappings(basepaths, http_api)  # type: ignore[no-untyped-call]

        # Create the Route53 RecordSetGroup resource
        record_set_group = self._construct_route53_recordsetgroup(route53_record_set_groups)  # type: ignore[no-untyped-call]

        return domain, basepath_resource_list, record_set_group

    def _construct_route53_recordsetgroup(self, route53_record_set_groups):  # type: ignore[no-untyped-def]
        if self.domain.get("Route53") is None:
            return
        route53 = self.domain.get("Route53")
        if not isinstance(route53, dict):
            raise InvalidResourceException(
                self.logical_id,
                "Invalid property type '{}' for Route53. "
                "Expected a map defines an Amazon Route 53 configuration'.".format(type(route53).__name__),
            )
        if route53.get("HostedZoneId") is None and route53.get("HostedZoneName") is None:
            raise InvalidResourceException(
                self.logical_id,
                "HostedZoneId or HostedZoneName is required to enable Route53 support on Custom Domains.",
            )

        logical_id_suffix = LogicalIdGenerator("", route53.get("HostedZoneId") or route53.get("HostedZoneName")).gen()  # type: ignore[no-untyped-call, no-untyped-call]
        logical_id = "RecordSetGroup" + logical_id_suffix

        record_set_group = route53_record_set_groups.get(logical_id)
        if not record_set_group:
            record_set_group = Route53RecordSetGroup(logical_id, attributes=self.passthrough_resource_attributes)
            if "HostedZoneId" in route53:
                record_set_group.HostedZoneId = route53.get("HostedZoneId")
            elif "HostedZoneName" in route53:
                record_set_group.HostedZoneName = route53.get("HostedZoneName")
            record_set_group.RecordSets = []
            route53_record_set_groups[logical_id] = record_set_group

        record_set_group.RecordSets += self._construct_record_sets_for_domain(self.domain)  # type: ignore[no-untyped-call]
        return record_set_group

    def _construct_basepath_mappings(self, basepaths, http_api):  # type: ignore[no-untyped-def]
        basepath_resource_list = []

        if basepaths is None:
            basepath_mapping = ApiGatewayV2ApiMapping(
                self.logical_id + "ApiMapping", attributes=self.passthrough_resource_attributes
            )
            basepath_mapping.DomainName = ref(self.domain.get("ApiDomainName"))
            basepath_mapping.ApiId = ref(http_api.logical_id)
            basepath_mapping.Stage = ref(http_api.logical_id + ".Stage")
            basepath_resource_list.extend([basepath_mapping])
        else:
            for path in basepaths:
                # search for invalid characters in the path and raise error if there are
                invalid_regex = r"[^0-9a-zA-Z\/\-\_]+"

                if not isinstance(path, str):
                    raise InvalidResourceException(self.logical_id, "Basepath must be a string.")

                if re.search(invalid_regex, path) is not None:
                    raise InvalidResourceException(self.logical_id, "Invalid Basepath name provided.")

                # ignore leading and trailing `/` in the path name
                path = path.strip("/")

                logical_id = "{}{}{}".format(self.logical_id, re.sub(r"[\-_/]+", "", path), "ApiMapping")
                basepath_mapping = ApiGatewayV2ApiMapping(logical_id, attributes=self.passthrough_resource_attributes)
                basepath_mapping.DomainName = ref(self.domain.get("ApiDomainName"))
                basepath_mapping.ApiId = ref(http_api.logical_id)
                basepath_mapping.Stage = ref(http_api.logical_id + ".Stage")
                basepath_mapping.ApiMappingKey = path
                basepath_resource_list.extend([basepath_mapping])
        return basepath_resource_list

    def _construct_record_sets_for_domain(self, domain):  # type: ignore[no-untyped-def]
        recordset_list = []
        recordset = {}
        route53 = domain.get("Route53")

        recordset["Name"] = domain.get("DomainName")
        recordset["Type"] = "A"
        recordset["AliasTarget"] = self._construct_alias_target(self.domain)  # type: ignore[no-untyped-call]
        recordset_list.extend([recordset])

        recordset_ipv6 = {}
        if route53.get("IpV6"):
            recordset_ipv6["Name"] = domain.get("DomainName")
            recordset_ipv6["Type"] = "AAAA"
            recordset_ipv6["AliasTarget"] = self._construct_alias_target(self.domain)  # type: ignore[no-untyped-call]
            recordset_list.extend([recordset_ipv6])

        return recordset_list

    def _construct_alias_target(self, domain):  # type: ignore[no-untyped-def]
        alias_target = {}
        route53 = domain.get("Route53")
        target_health = route53.get("EvaluateTargetHealth")

        if target_health is not None:
            alias_target["EvaluateTargetHealth"] = target_health
        if domain.get("EndpointConfiguration") == "REGIONAL":
            alias_target["HostedZoneId"] = fnGetAtt(self.domain.get("ApiDomainName"), "RegionalHostedZoneId")
            alias_target["DNSName"] = fnGetAtt(self.domain.get("ApiDomainName"), "RegionalDomainName")
        else:
            raise InvalidResourceException(
                self.logical_id,
                "Only REGIONAL endpoint is supported on HTTP APIs.",
            )
        return alias_target

    def _add_auth(self):  # type: ignore[no-untyped-def]
        """
        Add Auth configuration to the OAS file, if necessary
        """
        if not self.auth:
            return

        if self.auth and not self.definition_body:
            raise InvalidResourceException(
                self.logical_id, "Auth works only with inline OpenApi specified in the 'DefinitionBody' property."
            )

        # Make sure keys in the dict are recognized
        if not all(key in AuthProperties._fields for key in self.auth.keys()):
            raise InvalidResourceException(self.logical_id, "Invalid value for 'Auth' property")

        if not OpenApiEditor.is_valid(self.definition_body):
            raise InvalidResourceException(
                self.logical_id,
                "Unable to add Auth configuration because 'DefinitionBody' does not contain a valid OpenApi definition.",
            )
        open_api_editor = OpenApiEditor(self.definition_body)  # type: ignore[no-untyped-call]
        auth_properties = AuthProperties(**self.auth)
        authorizers = self._get_authorizers(auth_properties.Authorizers, auth_properties.EnableIamAuthorizer)  # type: ignore[no-untyped-call]

        # authorizers is guaranteed to return a value or raise an exception
        open_api_editor.add_authorizers_security_definitions(authorizers)  # type: ignore[no-untyped-call]
        self._set_default_authorizer(  # type: ignore[no-untyped-call]
            open_api_editor, authorizers, auth_properties.DefaultAuthorizer, auth_properties.Authorizers
        )
        self.definition_body = open_api_editor.openapi

    def _add_tags(self):  # type: ignore[no-untyped-def]
        """
        Adds tags to the Http Api, including a default SAM tag.
        """
        if self.tags and not self.definition_body:
            raise InvalidResourceException(
                self.logical_id, "Tags works only with inline OpenApi specified in the 'DefinitionBody' property."
            )

        if not self.definition_body:
            return

        if self.tags and not OpenApiEditor.is_valid(self.definition_body):
            raise InvalidResourceException(
                self.logical_id,
                "Unable to add `Tags` because 'DefinitionBody' does not contain a valid OpenApi definition.",
            )
        if not OpenApiEditor.is_valid(self.definition_body):
            return

        if not self.tags:
            self.tags = {}
        self.tags[HttpApiTagName] = "SAM"

        open_api_editor = OpenApiEditor(self.definition_body)  # type: ignore[no-untyped-call]

        # authorizers is guaranteed to return a value or raise an exception
        open_api_editor.add_tags(self.tags)  # type: ignore[no-untyped-call]
        self.definition_body = open_api_editor.openapi

    def _set_default_authorizer(self, open_api_editor, authorizers, default_authorizer, api_authorizers):  # type: ignore[no-untyped-def]
        """
        Sets the default authorizer if one is given in the template
        :param open_api_editor: editor object that contains the OpenApi definition
        :param authorizers: authorizer definitions converted from the API auth section
        :param default_authorizer: name of the default authorizer
        :param api_authorizers: API auth section authorizer defintions
        """
        if not default_authorizer:
            return

        if is_intrinsic_no_value(default_authorizer):
            return

        if is_intrinsic(default_authorizer):
            raise InvalidResourceException(
                self.logical_id,
                "Unable to set DefaultAuthorizer because intrinsic functions are not supported for this field.",
            )

        if not authorizers.get(default_authorizer):
            raise InvalidResourceException(
                self.logical_id,
                "Unable to set DefaultAuthorizer because '"
                + default_authorizer
                + "' was not defined in 'Authorizers'.",
            )

        for path in open_api_editor.iter_on_path():
            open_api_editor.set_path_default_authorizer(
                path, default_authorizer, authorizers=authorizers, api_authorizers=api_authorizers
            )

    def _get_authorizers(self, authorizers_config, enable_iam_authorizer=False):  # type: ignore[no-untyped-def]
        """
        Returns all authorizers for an API as an ApiGatewayV2Authorizer object
        :param authorizers_config: authorizer configuration from the API Auth section
        :param enable_iam_authorizer: if True add an "AWS_IAM" authorizer
        """
        authorizers = {}

        if enable_iam_authorizer is True:
            authorizers["AWS_IAM"] = ApiGatewayV2Authorizer(is_aws_iam_authorizer=True)  # type: ignore[no-untyped-call]

        # If all the customer wants to do is enable the IAM authorizer the authorizers_config will be None.
        if not authorizers_config:
            return authorizers

        if not isinstance(authorizers_config, dict):
            raise InvalidResourceException(self.logical_id, "Authorizers must be a dictionary.")

        for authorizer_name, authorizer in authorizers_config.items():
            if not isinstance(authorizer, dict):
                raise InvalidResourceException(
                    self.logical_id, "Authorizer %s must be a dictionary." % (authorizer_name)
                )

            if "OpenIdConnectUrl" in authorizer:
                raise InvalidResourceException(
                    self.logical_id,
                    "'OpenIdConnectUrl' is no longer a supported property for authorizer '%s'. Please refer to the AWS SAM documentation."
                    % (authorizer_name),
                )
            authorizers[authorizer_name] = ApiGatewayV2Authorizer(  # type: ignore[no-untyped-call]
                api_logical_id=self.logical_id,
                name=authorizer_name,
                authorization_scopes=authorizer.get("AuthorizationScopes"),
                jwt_configuration=authorizer.get("JwtConfiguration"),
                id_source=authorizer.get("IdentitySource"),
                function_arn=authorizer.get("FunctionArn"),
                function_invoke_role=authorizer.get("FunctionInvokeRole"),
                identity=authorizer.get("Identity"),
                authorizer_payload_format_version=authorizer.get("AuthorizerPayloadFormatVersion"),
                enable_simple_responses=authorizer.get("EnableSimpleResponses"),
            )
        return authorizers

    def _construct_body_s3_dict(self):  # type: ignore[no-untyped-def]
        """
        Constructs the HttpApi's `BodyS3Location property`, from the SAM Api's DefinitionUri property.
        :returns: a BodyS3Location dict, containing the S3 Bucket, Key, and Version of the OpenApi definition
        :rtype: dict
        """
        if isinstance(self.definition_uri, dict):
            if not self.definition_uri.get("Bucket", None) or not self.definition_uri.get("Key", None):
                # DefinitionUri is a dictionary but does not contain Bucket or Key property
                raise InvalidResourceException(
                    self.logical_id, "'DefinitionUri' requires Bucket and Key properties to be specified."
                )
            s3_pointer = self.definition_uri

        else:
            # DefinitionUri is a string
            s3_pointer = parse_s3_uri(self.definition_uri)  # type: ignore[no-untyped-call]
            if s3_pointer is None:
                raise InvalidResourceException(
                    self.logical_id,
                    "'DefinitionUri' is not a valid S3 Uri of the form "
                    "'s3://bucket/key' with optional versionId query parameter.",
                )

        body_s3 = {"Bucket": s3_pointer["Bucket"], "Key": s3_pointer["Key"]}
        if "Version" in s3_pointer:
            body_s3["Version"] = s3_pointer["Version"]
        return body_s3

    def _construct_stage(self):  # type: ignore[no-untyped-def]
        """Constructs and returns the ApiGatewayV2 Stage.

        :returns: the Stage to which this SAM Api corresponds
        :rtype: model.apigatewayv2.ApiGatewayV2Stage
        """

        # If there are no special configurations, don't create a stage and use the default
        if (
            not self.stage_name
            and not self.stage_variables
            and not self.access_log_settings
            and not self.default_route_settings
            and not self.route_settings
        ):
            return

        # If StageName is some intrinsic function, then don't prefix the Stage's logical ID
        # This will NOT create duplicates because we allow only ONE stage per API resource
        stage_name_prefix = self.stage_name if isinstance(self.stage_name, str) else ""
        if stage_name_prefix.isalnum():
            stage_logical_id = self.logical_id + stage_name_prefix + "Stage"
        elif stage_name_prefix == DefaultStageName:
            stage_logical_id = self.logical_id + "ApiGatewayDefaultStage"
        else:
            generator = LogicalIdGenerator(self.logical_id + "Stage", stage_name_prefix)  # type: ignore[no-untyped-call]
            stage_logical_id = generator.gen()  # type: ignore[no-untyped-call]
        stage = ApiGatewayV2Stage(stage_logical_id, attributes=self.passthrough_resource_attributes)
        stage.ApiId = ref(self.logical_id)
        stage.StageName = self.stage_name
        stage.StageVariables = self.stage_variables
        stage.AccessLogSettings = self.access_log_settings
        stage.DefaultRouteSettings = self.default_route_settings
        stage.Tags = self.tags
        stage.AutoDeploy = True
        stage.RouteSettings = self.route_settings

        return stage

    def _add_description(self):  # type: ignore[no-untyped-def]
        """Add description to DefinitionBody if Description property is set in SAM"""
        if not self.description:
            return

        if not self.definition_body:
            raise InvalidResourceException(
                self.logical_id,
                "Description works only with inline OpenApi specified in the 'DefinitionBody' property.",
            )
        if self.definition_body.get("info", {}).get("description"):
            raise InvalidResourceException(
                self.logical_id,
                "Unable to set Description because it is already defined within inline OpenAPI specified in the "
                "'DefinitionBody' property.",
            )

        open_api_editor = OpenApiEditor(self.definition_body)  # type: ignore[no-untyped-call]
        open_api_editor.add_description(self.description)  # type: ignore[no-untyped-call]
        self.definition_body = open_api_editor.openapi

    @cw_timer(prefix="Generator", name="HttpApi")  # type: ignore[no-untyped-call]
    def to_cloudformation(self, route53_record_set_groups):  # type: ignore[no-untyped-def]
        """Generates CloudFormation resources from a SAM HTTP API resource

        :returns: a tuple containing the HttpApi and Stage for an empty Api.
        :rtype: tuple
        """
        http_api = self._construct_http_api()  # type: ignore[no-untyped-call]
        domain, basepath_mapping, route53 = self._construct_api_domain(http_api, route53_record_set_groups)  # type: ignore[no-untyped-call]
        stage = self._construct_stage()  # type: ignore[no-untyped-call]

        return http_api, stage, domain, basepath_mapping, route53
