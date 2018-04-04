from samtranslator.model import PropertyType, Resource
from samtranslator.model.types import is_type, one_of, is_str, list_of, any_type
from samtranslator.model.intrinsics import fnGetAtt, ref


class LambdaFunction(Resource):
    resource_type = 'AWS::Lambda::Function'
    property_types = {
            'Code': PropertyType(True, is_type(dict)),
            'DeadLetterConfig': PropertyType(False, is_type(dict)),
            'Description': PropertyType(False, is_str()),
            'FunctionName': PropertyType(False, is_str()),
            'Handler': PropertyType(True, is_str()),
            'MemorySize': PropertyType(False, is_type(int)),
            'Role': PropertyType(False, is_str()),
            'Runtime': PropertyType(False, is_str()),
            'Timeout': PropertyType(False, is_type(int)),
            'VpcConfig': PropertyType(False, is_type(dict)),
            'Environment': PropertyType(False, is_type(dict)),
            'Tags': PropertyType(False, list_of(is_type(dict))),
            'TracingConfig': PropertyType(False, is_type(dict)),
            'KmsKeyArn': PropertyType(False, one_of(is_type(dict), is_str())),
            'ReservedConcurrentExecutions': PropertyType(False, any_type())
    }

    runtime_attrs = {
        "name": lambda self: ref(self.logical_id),
        "arn": lambda self: fnGetAtt(self.logical_id, "Arn")
    }

class LambdaVersion(Resource):
    resource_type = 'AWS::Lambda::Version'
    property_types = {
            'CodeSha256': PropertyType(False, is_str()),
            'Description': PropertyType(False, is_str()),
            'FunctionName': PropertyType(True, one_of(is_str(), is_type(dict)))
    }

    runtime_attrs = {
        "arn": lambda self: ref(self.logical_id),
        "version": lambda self: fnGetAtt(self.logical_id, "Version")
    }

class LambdaAlias(Resource):
    resource_type = 'AWS::Lambda::Alias'
    property_types = {
            'Description': PropertyType(False, is_str()),
            'Name': PropertyType(False, is_str()),
            'FunctionName': PropertyType(True, one_of(is_str(), is_type(dict))),
            'FunctionVersion': PropertyType(True, one_of(is_str(), is_type(dict)))
    }

    runtime_attrs = {
        "arn": lambda self: ref(self.logical_id)
    }

class LambdaEventSourceMapping(Resource):
    resource_type = 'AWS::Lambda::EventSourceMapping'
    property_types = {
            'BatchSize': PropertyType(False, is_type(int)),
            'Enabled': PropertyType(False, is_type(bool)),
            'EventSourceArn': PropertyType(True, is_str()),
            'FunctionName': PropertyType(True, is_str()),
            'StartingPosition': PropertyType(True, is_str())
    }

    runtime_attrs = {
        "name": lambda self: ref(self.logical_id)
    }

class LambdaPermission(Resource):
    resource_type = 'AWS::Lambda::Permission'
    property_types = {
            'Action': PropertyType(True, is_str()),
            'FunctionName': PropertyType(True, is_str()),
            'Principal': PropertyType(True, is_str()),
            'SourceAccount': PropertyType(False, is_str()),
            'SourceArn': PropertyType(False, is_str())
    }
