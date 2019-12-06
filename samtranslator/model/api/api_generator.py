from collections import namedtuple
from six import string_types
from samtranslator.model.intrinsics import ref, fnGetAtt
from samtranslator.model.apigateway import (ApiGatewayDeployment, ApiGatewayRestApi,
                                            ApiGatewayStage, ApiGatewayAuthorizer,
                                            ApiGatewayResponse, ApiGatewayDomainName,
                                            ApiGatewayBasePathMapping)
from samtranslator.model.route53 import Route53RecordSetGroup
from samtranslator.model.exceptions import InvalidResourceException
from samtranslator.model.s3_utils.uri_parser import parse_s3_uri
from samtranslator.region_configuration import RegionConfiguration
from samtranslator.swagger.swagger import SwaggerEditor
from samtranslator.model.intrinsics import is_instrinsic, fnSub
from samtranslator.model.lambda_ import LambdaPermission
from samtranslator.translator import logical_id_generator
from samtranslator.translator.arn_generator import ArnGenerator
from samtranslator.model.tags.resource_tagging import get_tag_list

_CORS_WILDCARD = "'*'"
CorsProperties = namedtuple("_CorsProperties", ["AllowMethods", "AllowHeaders", "AllowOrigin", "MaxAge",
                                                "AllowCredentials"])
# Default the Cors Properties to '*' wildcard and False AllowCredentials. Other properties are actually Optional
CorsProperties.__new__.__defaults__ = (None, None, _CORS_WILDCARD, None, False)

AuthProperties = namedtuple("_AuthProperties",
                            ["Authorizers", "DefaultAuthorizer", "InvokeRole", "AddDefaultAuthorizerToCorsPreflight",
                             "ApiKeyRequired", "ResourcePolicy"])
AuthProperties.__new__.__defaults__ = (None, None, None, True, None, None)

GatewayResponseProperties = ["ResponseParameters", "ResponseTemplates", "StatusCode"]


class ApiGenerator(object):

    def __init__(self, logical_id, cache_cluster_enabled, cache_cluster_size, variables, depends_on,
                 definition_body, definition_uri, name, stage_name, tags=None, endpoint_configuration=None,
                 method_settings=None, binary_media=None, minimum_compression_size=None, cors=None,
                 auth=None, gateway_responses=None, access_log_setting=None, canary_setting=None,
                 tracing_enabled=None, resource_attributes=None, passthrough_resource_attributes=None,
                 open_api_version=None, models=None, domain=None):
        """Constructs an API Generator class that generates API Gateway resources

        :param logical_id: Logical id of the SAM API Resource
        :param cache_cluster_enabled: Whether cache cluster is enabled
        :param cache_cluster_size: Size of the cache cluster
        :param variables: API Gateway Variables
        :param depends_on: Any resources that need to be depended on
        :param definition_body: API definition
        :param definition_uri: URI to API definition
        :param name: Name of the API Gateway resource
        :param stage_name: Name of the Stage
        :param tags: Stage Tags
        :param access_log_setting: Whether to send access logs and where for Stage
        :param canary_setting: Canary Setting for Stage
        :param tracing_enabled: Whether active tracing with X-ray is enabled
        :param resource_attributes: Resource attributes to add to API resources
        :param passthrough_resource_attributes: Attributes such as `Condition` that are added to derived resources
        :param models: Model definitions to be used by API methods
        """
        self.logical_id = logical_id
        self.cache_cluster_enabled = cache_cluster_enabled
        self.cache_cluster_size = cache_cluster_size
        self.variables = variables
        self.depends_on = depends_on
        self.definition_body = definition_body
        self.definition_uri = definition_uri
        self.name = name
        self.stage_name = stage_name
        self.tags = tags
        self.endpoint_configuration = endpoint_configuration
        self.method_settings = method_settings
        self.binary_media = binary_media
        self.minimum_compression_size = minimum_compression_size
        self.cors = cors
        self.auth = auth
        self.gateway_responses = gateway_responses
        self.access_log_setting = access_log_setting
        self.canary_setting = canary_setting
        self.tracing_enabled = tracing_enabled
        self.resource_attributes = resource_attributes
        self.passthrough_resource_attributes = passthrough_resource_attributes
        self.open_api_version = open_api_version
        self.remove_extra_stage = open_api_version
        self.models = models
        self.domain = domain

    def _construct_rest_api(self):
        """Constructs and returns the ApiGateway RestApi.

        :returns: the RestApi to which this SAM Api corresponds
        :rtype: model.apigateway.ApiGatewayRestApi
        """
        rest_api = ApiGatewayRestApi(self.logical_id, depends_on=self.depends_on, attributes=self.resource_attributes)
        # NOTE: For backwards compatibility we need to retain BinaryMediaTypes on the CloudFormation Property
        # Removing this and only setting x-amazon-apigateway-binary-media-types results in other issues.
        rest_api.BinaryMediaTypes = self.binary_media
        rest_api.MinimumCompressionSize = self.minimum_compression_size

        if self.endpoint_configuration:
            self._set_endpoint_configuration(rest_api, self.endpoint_configuration)

        elif not RegionConfiguration.is_apigw_edge_configuration_supported():
            # Since this region does not support EDGE configuration, we explicitly set the endpoint type
            # to Regional which is the only supported config.
            self._set_endpoint_configuration(rest_api, "REGIONAL")

        if self.definition_uri and self.definition_body:
            raise InvalidResourceException(self.logical_id,
                                           "Specify either 'DefinitionUri' or 'DefinitionBody' property and not both")

        if self.open_api_version:
            if not SwaggerEditor.safe_compare_regex_with_string(SwaggerEditor.get_openapi_versions_supported_regex(),
                                                                self.open_api_version):
                raise InvalidResourceException(self.logical_id,
                                               "The OpenApiVersion value must be of the format \"3.0.0\"")

        self._add_cors()
        self._add_auth()
        self._add_gateway_responses()
        self._add_binary_media_types()
        self._add_models()

        if self.definition_uri:
            rest_api.BodyS3Location = self._construct_body_s3_dict()
        elif self.definition_body:
            # # Post Process OpenApi Auth Settings
            self.definition_body = self._openapi_postprocess(self.definition_body)
            rest_api.Body = self.definition_body

        if self.name:
            rest_api.Name = self.name

        return rest_api

    def _construct_body_s3_dict(self):
        """Constructs the RestApi's `BodyS3Location property`_, from the SAM Api's DefinitionUri property.

        :returns: a BodyS3Location dict, containing the S3 Bucket, Key, and Version of the Swagger definition
        :rtype: dict
        """
        if isinstance(self.definition_uri, dict):
            if not self.definition_uri.get("Bucket", None) or not self.definition_uri.get("Key", None):
                # DefinitionUri is a dictionary but does not contain Bucket or Key property
                raise InvalidResourceException(self.logical_id,
                                               "'DefinitionUri' requires Bucket and Key properties to be specified")
            s3_pointer = self.definition_uri

        else:

            # DefinitionUri is a string
            s3_pointer = parse_s3_uri(self.definition_uri)
            if s3_pointer is None:
                raise InvalidResourceException(self.logical_id,
                                               '\'DefinitionUri\' is not a valid S3 Uri of the form '
                                               '"s3://bucket/key" with optional versionId query parameter.')

        body_s3 = {
            'Bucket': s3_pointer['Bucket'],
            'Key': s3_pointer['Key']
        }
        if 'Version' in s3_pointer:
            body_s3['Version'] = s3_pointer['Version']
        return body_s3

    def _construct_deployment(self, rest_api):
        """Constructs and returns the ApiGateway Deployment.

        :param model.apigateway.ApiGatewayRestApi rest_api: the RestApi for this Deployment
        :returns: the Deployment to which this SAM Api corresponds
        :rtype: model.apigateway.ApiGatewayDeployment
        """
        deployment = ApiGatewayDeployment(self.logical_id + 'Deployment',
                                          attributes=self.passthrough_resource_attributes)
        deployment.RestApiId = rest_api.get_runtime_attr('rest_api_id')
        if not self.remove_extra_stage:
            deployment.StageName = 'Stage'

        return deployment

    def _construct_stage(self, deployment, swagger):
        """Constructs and returns the ApiGateway Stage.

        :param model.apigateway.ApiGatewayDeployment deployment: the Deployment for this Stage
        :returns: the Stage to which this SAM Api corresponds
        :rtype: model.apigateway.ApiGatewayStage
        """

        # If StageName is some intrinsic function, then don't prefix the Stage's logical ID
        # This will NOT create duplicates because we allow only ONE stage per API resource
        stage_name_prefix = self.stage_name if isinstance(self.stage_name, string_types) else ""
        if stage_name_prefix.isalnum():
            stage_logical_id = self.logical_id + stage_name_prefix + 'Stage'
        else:
            generator = logical_id_generator.LogicalIdGenerator(self.logical_id + 'Stage', stage_name_prefix)
            stage_logical_id = generator.gen()
        stage = ApiGatewayStage(stage_logical_id,
                                attributes=self.passthrough_resource_attributes)
        stage.RestApiId = ref(self.logical_id)
        stage.update_deployment_ref(deployment.logical_id)
        stage.StageName = self.stage_name
        stage.CacheClusterEnabled = self.cache_cluster_enabled
        stage.CacheClusterSize = self.cache_cluster_size
        stage.Variables = self.variables
        stage.MethodSettings = self.method_settings
        stage.AccessLogSetting = self.access_log_setting
        stage.CanarySetting = self.canary_setting
        stage.TracingEnabled = self.tracing_enabled

        if swagger is not None:
            deployment.make_auto_deployable(stage, self.remove_extra_stage, swagger, self.domain)

        if self.tags is not None:
            stage.Tags = get_tag_list(self.tags)

        return stage

    def _construct_api_domain(self, rest_api):
        """
        Constructs and returns the ApiGateway Domain and BasepathMapping
        """
        if self.domain is None:
            return None, None, None

        if self.domain.get('DomainName') is None or \
           self.domain.get('CertificateArn') is None:
            raise InvalidResourceException(self.logical_id,
                                           "Custom Domains only works if both DomainName and CertificateArn"
                                           " are provided")

        self.domain['ApiDomainName'] = "{}{}".format('ApiGatewayDomainName',
                                                     logical_id_generator.
                                                     LogicalIdGenerator("", self.domain.get('DomainName')).gen())

        domain = ApiGatewayDomainName(self.domain.get('ApiDomainName'),
                                      attributes=self.passthrough_resource_attributes)
        domain.DomainName = self.domain.get('DomainName')
        endpoint = self.domain.get('EndpointConfiguration')

        if endpoint is None:
            endpoint = 'REGIONAL'
            self.domain['EndpointConfiguration'] = 'REGIONAL'
        elif endpoint not in ['EDGE', 'REGIONAL']:
            raise InvalidResourceException(self.logical_id,
                                           "EndpointConfiguration for Custom Domains must be"
                                           " one of {}".format(['EDGE', 'REGIONAL']))

        if endpoint == 'REGIONAL':
            domain.RegionalCertificateArn = self.domain.get('CertificateArn')
        else:
            domain.CertificateArn = self.domain.get('CertificateArn')

        domain.EndpointConfiguration = {"Types": [endpoint]}

        # Create BasepathMappings
        if self.domain.get('BasePath') and isinstance(self.domain.get('BasePath'), string_types):
            basepaths = [self.domain.get('BasePath')]
        elif self.domain.get('BasePath') and isinstance(self.domain.get('BasePath'), list):
            basepaths = self.domain.get('BasePath')
        else:
            basepaths = None

        basepath_resource_list = []

        if basepaths is None:
            basepath_mapping = ApiGatewayBasePathMapping(self.logical_id + 'BasePathMapping',
                                                         attributes=self.passthrough_resource_attributes)
            basepath_mapping.DomainName = self.domain.get('DomainName')
            basepath_mapping.RestApiId = ref(rest_api.logical_id)
            basepath_mapping.Stage = ref(rest_api.logical_id + '.Stage')
            basepath_resource_list.extend([basepath_mapping])
        else:
            for path in basepaths:
                path = ''.join(e for e in path if e.isalnum())
                logical_id = "{}{}{}".format(self.logical_id, path, 'BasePathMapping')
                basepath_mapping = ApiGatewayBasePathMapping(logical_id,
                                                             attributes=self.passthrough_resource_attributes)
                basepath_mapping.DomainName = self.domain.get('DomainName')
                basepath_mapping.RestApiId = ref(rest_api.logical_id)
                basepath_mapping.Stage = ref(rest_api.logical_id + '.Stage')
                basepath_mapping.BasePath = path
                basepath_resource_list.extend([basepath_mapping])

        # Create the Route53 RecordSetGroup resource
        record_set_group = None
        if self.domain.get('Route53') is not None:
            route53 = self.domain.get('Route53')
            if route53.get('HostedZoneId') is None:
                raise InvalidResourceException(self.logical_id,
                                               "HostedZoneId is required to enable Route53 support on Custom Domains.")
            logical_id = logical_id_generator.LogicalIdGenerator("", route53.get('HostedZoneId')).gen()
            record_set_group = Route53RecordSetGroup('RecordSetGroup' + logical_id,
                                                     attributes=self.passthrough_resource_attributes)
            record_set_group.HostedZoneId = route53.get('HostedZoneId')
            record_set_group.RecordSets = self._construct_record_sets_for_domain(self.domain)

        return domain, basepath_resource_list, record_set_group

    def _construct_record_sets_for_domain(self, domain):
        recordset_list = []
        recordset = {}
        route53 = domain.get('Route53')

        recordset['Name'] = domain.get('DomainName')
        recordset['Type'] = 'A'
        recordset['AliasTarget'] = self._construct_alias_target(self.domain)
        recordset_list.extend([recordset])

        recordset_ipv6 = {}
        if route53.get('IpV6') is not None and route53.get('IpV6') is True:
            recordset_ipv6['Name'] = domain.get('DomainName')
            recordset_ipv6['Type'] = 'AAAA'
            recordset_ipv6['AliasTarget'] = self._construct_alias_target(self.domain)
            recordset_list.extend([recordset_ipv6])

        return recordset_list

    def _construct_alias_target(self, domain):
        alias_target = {}
        route53 = domain.get('Route53')
        target_health = route53.get('EvaluateTargetHealth')

        if target_health is not None:
            alias_target['EvaluateTargetHealth'] = target_health
        if domain.get('EndpointConfiguration') == 'REGIONAL':
            alias_target['HostedZoneId'] = fnGetAtt(self.domain.get('ApiDomainName'), 'RegionalHostedZoneId')
            alias_target['DNSName'] = fnGetAtt(self.domain.get('ApiDomainName'), 'RegionalDomainName')
        else:
            if route53.get('DistributionDomainName') is None:
                route53['DistributionDomainName'] = fnGetAtt(self.domain.get('ApiDomainName'), 'DistributionDomainName')
            alias_target['HostedZoneId'] = 'Z2FDTNDATAQYW2'
            alias_target['DNSName'] = route53.get('DistributionDomainName')
        return alias_target

    def to_cloudformation(self):
        """Generates CloudFormation resources from a SAM API resource

        :returns: a tuple containing the RestApi, Deployment, and Stage for an empty Api.
        :rtype: tuple
        """
        rest_api = self._construct_rest_api()
        domain, basepath_mapping, route53 = self._construct_api_domain(rest_api)
        deployment = self._construct_deployment(rest_api)

        swagger = None
        if rest_api.Body is not None:
            swagger = rest_api.Body
        elif rest_api.BodyS3Location is not None:
            swagger = rest_api.BodyS3Location

        stage = self._construct_stage(deployment, swagger)
        permissions = self._construct_authorizer_lambda_permission()

        return rest_api, deployment, stage, permissions, domain, basepath_mapping, route53

    def _add_cors(self):
        """
        Add CORS configuration to the Swagger file, if necessary
        """

        INVALID_ERROR = "Invalid value for 'Cors' property"

        if not self.cors:
            return

        if self.cors and not self.definition_body:
            raise InvalidResourceException(self.logical_id,
                                           "Cors works only with inline Swagger specified in "
                                           "'DefinitionBody' property")

        if isinstance(self.cors, string_types) or is_instrinsic(self.cors):
            # Just set Origin property. Others will be defaults
            properties = CorsProperties(AllowOrigin=self.cors)
        elif isinstance(self.cors, dict):

            # Make sure keys in the dict are recognized
            if not all(key in CorsProperties._fields for key in self.cors.keys()):
                raise InvalidResourceException(self.logical_id, INVALID_ERROR)

            properties = CorsProperties(**self.cors)

        else:
            raise InvalidResourceException(self.logical_id, INVALID_ERROR)

        if not SwaggerEditor.is_valid(self.definition_body):
            raise InvalidResourceException(self.logical_id, "Unable to add Cors configuration because "
                                                            "'DefinitionBody' does not contain a valid Swagger")

        if properties.AllowCredentials is True and properties.AllowOrigin == _CORS_WILDCARD:
            raise InvalidResourceException(self.logical_id, "Unable to add Cors configuration because "
                                                            "'AllowCredentials' can not be true when "
                                                            "'AllowOrigin' is \"'*'\" or not set")

        editor = SwaggerEditor(self.definition_body)
        for path in editor.iter_on_path():
            editor.add_cors(path, properties.AllowOrigin, properties.AllowHeaders, properties.AllowMethods,
                            max_age=properties.MaxAge, allow_credentials=properties.AllowCredentials)

        # Assign the Swagger back to template
        self.definition_body = editor.swagger

    def _add_binary_media_types(self):
        """
        Add binary media types to Swagger
        """

        if not self.binary_media:
            return

        # We don't raise an error here like we do for similar cases because that would be backwards incompatible
        if self.binary_media and not self.definition_body:
            return

        editor = SwaggerEditor(self.definition_body)
        editor.add_binary_media_types(self.binary_media)

        # Assign the Swagger back to template
        self.definition_body = editor.swagger

    def _add_auth(self):
        """
        Add Auth configuration to the Swagger file, if necessary
        """

        if not self.auth:
            return

        if self.auth and not self.definition_body:
            raise InvalidResourceException(self.logical_id,
                                           "Auth works only with inline Swagger specified in "
                                           "'DefinitionBody' property")

        # Make sure keys in the dict are recognized
        if not all(key in AuthProperties._fields for key in self.auth.keys()):
            raise InvalidResourceException(
                self.logical_id, "Invalid value for 'Auth' property")

        if not SwaggerEditor.is_valid(self.definition_body):
            raise InvalidResourceException(self.logical_id, "Unable to add Auth configuration because "
                                                            "'DefinitionBody' does not contain a valid Swagger")
        swagger_editor = SwaggerEditor(self.definition_body)
        auth_properties = AuthProperties(**self.auth)
        authorizers = self._get_authorizers(auth_properties.Authorizers, auth_properties.DefaultAuthorizer)

        if authorizers:
            swagger_editor.add_authorizers_security_definitions(authorizers)
            self._set_default_authorizer(swagger_editor, authorizers, auth_properties.DefaultAuthorizer,
                                         auth_properties.AddDefaultAuthorizerToCorsPreflight,
                                         auth_properties.Authorizers)

        if auth_properties.ApiKeyRequired:
            swagger_editor.add_apikey_security_definition()
            self._set_default_apikey_required(swagger_editor)

        if auth_properties.ResourcePolicy:
            for path in swagger_editor.iter_on_path():
                swagger_editor.add_resource_policy(auth_properties.ResourcePolicy, path,
                                                   self.logical_id, self.stage_name)

        self.definition_body = self._openapi_postprocess(swagger_editor.swagger)

    def _add_gateway_responses(self):
        """
        Add Gateway Response configuration to the Swagger file, if necessary
        """

        if not self.gateway_responses:
            return

        if self.gateway_responses and not self.definition_body:
            raise InvalidResourceException(
                self.logical_id, "GatewayResponses works only with inline Swagger specified in "
                                 "'DefinitionBody' property")

        # Make sure keys in the dict are recognized
        for responses_key, responses_value in self.gateway_responses.items():
            for response_key in responses_value.keys():
                if response_key not in GatewayResponseProperties:
                    raise InvalidResourceException(
                        self.logical_id,
                        "Invalid property '{}' in 'GatewayResponses' property '{}'".format(response_key, responses_key))

        if not SwaggerEditor.is_valid(self.definition_body):
            raise InvalidResourceException(
                self.logical_id, "Unable to add Auth configuration because "
                                 "'DefinitionBody' does not contain a valid Swagger")

        swagger_editor = SwaggerEditor(self.definition_body)

        gateway_responses = {}
        for response_type, response in self.gateway_responses.items():
            gateway_responses[response_type] = ApiGatewayResponse(
                api_logical_id=self.logical_id,
                response_parameters=response.get('ResponseParameters', {}),
                response_templates=response.get('ResponseTemplates', {}),
                status_code=response.get('StatusCode', None)
            )

        if gateway_responses:
            swagger_editor.add_gateway_responses(gateway_responses)

        # Assign the Swagger back to template
        self.definition_body = swagger_editor.swagger

    def _add_models(self):
        """
        Add Model definitions to the Swagger file, if necessary
        :return:
        """

        if not self.models:
            return

        if self.models and not self.definition_body:
            raise InvalidResourceException(self.logical_id,
                                           "Models works only with inline Swagger specified in "
                                           "'DefinitionBody' property")

        if not SwaggerEditor.is_valid(self.definition_body):
            raise InvalidResourceException(self.logical_id, "Unable to add Models definitions because "
                                                            "'DefinitionBody' does not contain a valid Swagger")

        if not all(isinstance(model, dict) for model in self.models.values()):
            raise InvalidResourceException(self.logical_id, "Invalid value for 'Models' property")

        swagger_editor = SwaggerEditor(self.definition_body)
        swagger_editor.add_models(self.models)

        # Assign the Swagger back to template

        self.definition_body = self._openapi_postprocess(swagger_editor.swagger)

    def _openapi_postprocess(self, definition_body):
        """
        Convert definitions to openapi 3 in definition body if OpenApiVersion flag is specified.

        If the is swagger defined in the definition body, we treat it as a swagger spec and dod not
        make any openapi 3 changes to it
        """
        if definition_body.get('swagger') is not None:
            return definition_body

        if definition_body.get('openapi') is not None and self.open_api_version is None:
            self.open_api_version = definition_body.get('openapi')

        if self.open_api_version and \
           SwaggerEditor.safe_compare_regex_with_string(SwaggerEditor.get_openapi_version_3_regex(),
                                                        self.open_api_version):
            if definition_body.get('securityDefinitions'):
                components = definition_body.get('components', {})
                components['securitySchemes'] = definition_body['securityDefinitions']
                definition_body['components'] = components
                del definition_body['securityDefinitions']
            if definition_body.get('definitions'):
                components = definition_body.get('components', {})
                components['schemas'] = definition_body['definitions']
                definition_body['components'] = components
                del definition_body['definitions']
        return definition_body

    def _get_authorizers(self, authorizers_config, default_authorizer=None):
        authorizers = {}
        if default_authorizer == 'AWS_IAM':
            authorizers[default_authorizer] = ApiGatewayAuthorizer(
                api_logical_id=self.logical_id,
                name=default_authorizer,
                is_aws_iam_authorizer=True
            )

        if not authorizers_config:
            if 'AWS_IAM' in authorizers:
                return authorizers
            return None

        if not isinstance(authorizers_config, dict):
            raise InvalidResourceException(self.logical_id,
                                           "Authorizers must be a dictionary")

        for authorizer_name, authorizer in authorizers_config.items():
            if not isinstance(authorizer, dict):
                raise InvalidResourceException(self.logical_id,
                                               "Authorizer %s must be a dictionary." % (authorizer_name))

            authorizers[authorizer_name] = ApiGatewayAuthorizer(
                api_logical_id=self.logical_id,
                name=authorizer_name,
                user_pool_arn=authorizer.get('UserPoolArn'),
                function_arn=authorizer.get('FunctionArn'),
                identity=authorizer.get('Identity'),
                function_payload_type=authorizer.get('FunctionPayloadType'),
                function_invoke_role=authorizer.get('FunctionInvokeRole'),
                authorization_scopes=authorizer.get("AuthorizationScopes")
            )
        return authorizers

    def _get_permission(self, authorizer_name, authorizer_lambda_function_arn):
        """Constructs and returns the Lambda Permission resource allowing the Authorizer to invoke the function.

        :returns: the permission resource
        :rtype: model.lambda_.LambdaPermission
        """
        rest_api = ApiGatewayRestApi(self.logical_id, depends_on=self.depends_on, attributes=self.resource_attributes)
        api_id = rest_api.get_runtime_attr('rest_api_id')

        partition = ArnGenerator.get_partition_name()
        resource = '${__ApiId__}/authorizers/*'
        source_arn = fnSub(ArnGenerator.generate_arn(partition=partition, service='execute-api', resource=resource),
                           {"__ApiId__": api_id})

        lambda_permission = LambdaPermission(self.logical_id + authorizer_name + 'AuthorizerPermission',
                                             attributes=self.passthrough_resource_attributes)
        lambda_permission.Action = 'lambda:invokeFunction'
        lambda_permission.FunctionName = authorizer_lambda_function_arn
        lambda_permission.Principal = 'apigateway.amazonaws.com'
        lambda_permission.SourceArn = source_arn

        return lambda_permission

    def _construct_authorizer_lambda_permission(self):
        if not self.auth:
            return []

        auth_properties = AuthProperties(**self.auth)
        authorizers = self._get_authorizers(auth_properties.Authorizers)

        if not authorizers:
            return []

        permissions = []

        for authorizer_name, authorizer in authorizers.items():
            # Construct permissions for Lambda Authorizers only
            if not authorizer.function_arn:
                continue

            permission = self._get_permission(authorizer_name, authorizer.function_arn)
            permissions.append(permission)

        return permissions

    def _set_default_authorizer(self, swagger_editor, authorizers, default_authorizer,
                                add_default_auth_to_preflight=True, api_authorizers=None):
        if not default_authorizer:
            return

        if not authorizers.get(default_authorizer) and default_authorizer != 'AWS_IAM':
            raise InvalidResourceException(self.logical_id, "Unable to set DefaultAuthorizer because '" +
                                           default_authorizer + "' was not defined in 'Authorizers'")

        for path in swagger_editor.iter_on_path():
            swagger_editor.set_path_default_authorizer(path, default_authorizer, authorizers=authorizers,
                                                       add_default_auth_to_preflight=add_default_auth_to_preflight,
                                                       api_authorizers=api_authorizers)

    def _set_default_apikey_required(self, swagger_editor):
        for path in swagger_editor.iter_on_path():
            swagger_editor.set_path_default_apikey_required(path)

    def _set_endpoint_configuration(self, rest_api, value):
        """
        Sets endpoint configuration property of AWS::ApiGateway::RestApi resource
        :param rest_api: RestApi resource
        :param string/dict value: Value to be set
        """

        rest_api.EndpointConfiguration = {"Types": [value]}
        rest_api.Parameters = {"endpointConfigurationTypes": value}
