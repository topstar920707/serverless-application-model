from typing import Any, Dict

from samtranslator.model import PropertyType, Resource
from samtranslator.model.types import IS_DICT, is_type, IS_STR, list_of
from samtranslator.model.intrinsics import ref, fnGetAtt


class IAMRole(Resource):
    resource_type = "AWS::IAM::Role"
    property_types = {
        "AssumeRolePolicyDocument": PropertyType(True, IS_DICT),
        "ManagedPolicyArns": PropertyType(False, is_type(list)),
        "Path": PropertyType(False, IS_STR),
        "Policies": PropertyType(False, is_type(list)),
        "PermissionsBoundary": PropertyType(False, IS_STR),
        "Tags": PropertyType(False, list_of(IS_DICT)),
    }

    runtime_attrs = {"name": lambda self: ref(self.logical_id), "arn": lambda self: fnGetAtt(self.logical_id, "Arn")}


class IAMManagedPolicy(Resource):
    resource_type = "AWS::IAM::ManagedPolicy"
    property_types = {
        "Description": PropertyType(False, IS_STR),
        "Groups": PropertyType(False, IS_STR),
        "PolicyDocument": PropertyType(True, IS_DICT),
        "ManagedPolicyName": PropertyType(False, IS_STR),
        "Path": PropertyType(False, IS_STR),
        "Roles": PropertyType(False, is_type(list)),
        "Users": PropertyType(False, list_of(IS_STR)),
    }


class IAMRolePolicies:
    @classmethod
    def construct_assume_role_policy_for_service_principal(cls, service_principal):  # type: ignore[no-untyped-def]
        document = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": ["sts:AssumeRole"],
                    "Effect": "Allow",
                    "Principal": {"Service": [service_principal]},
                }
            ],
        }
        return document

    @classmethod
    def step_functions_start_execution_role_policy(cls, state_machine_arn, logical_id):  # type: ignore[no-untyped-def]
        document = {
            "PolicyName": logical_id + "StartExecutionPolicy",
            "PolicyDocument": {
                "Statement": [{"Action": "states:StartExecution", "Effect": "Allow", "Resource": state_machine_arn}]
            },
        }
        return document

    @classmethod
    def stepfunctions_assume_role_policy(cls):  # type: ignore[no-untyped-def]
        document = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": ["sts:AssumeRole"],
                    "Effect": "Allow",
                    "Principal": {"Service": ["states.amazonaws.com"]},
                }
            ],
        }
        return document

    @classmethod
    def cloud_watch_log_assume_role_policy(cls):  # type: ignore[no-untyped-def]
        document = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": ["sts:AssumeRole"],
                    "Effect": "Allow",
                    "Principal": {"Service": ["apigateway.amazonaws.com"]},
                }
            ],
        }
        return document

    @classmethod
    def scheduler_assume_role_policy(cls) -> Dict[str, Any]:
        document = {
            "Version": "2012-10-17",
            "Statement": [
                {"Action": ["sts:AssumeRole"], "Effect": "Allow", "Principal": {"Service": ["scheduler.amazonaws.com"]}}
            ],
        }
        return document

    @classmethod
    def lambda_assume_role_policy(cls) -> Dict[str, Any]:
        document = {
            "Version": "2012-10-17",
            "Statement": [
                {"Action": ["sts:AssumeRole"], "Effect": "Allow", "Principal": {"Service": ["lambda.amazonaws.com"]}}
            ],
        }
        return document

    @classmethod
    def dead_letter_queue_policy(cls, action: Any, resource: Any) -> Dict[str, Any]:
        """Return the DeadLetterQueue Policy to be added to the LambdaRole
        :returns: Policy for the DeadLetterQueue
        :rtype: Dict
        """
        return {
            "PolicyName": "DeadLetterQueuePolicy",
            "PolicyDocument": {
                "Version": "2012-10-17",
                "Statement": [{"Action": action, "Resource": resource, "Effect": "Allow"}],
            },
        }

    @classmethod
    def sqs_send_message_role_policy(cls, queue_arn: Any, logical_id: str) -> Dict[str, Any]:
        document = {
            "PolicyName": logical_id + "SQSPolicy",
            "PolicyDocument": {"Statement": [{"Action": "sqs:SendMessage", "Effect": "Allow", "Resource": queue_arn}]},
        }
        return document

    @classmethod
    def sns_publish_role_policy(cls, topic_arn: Any, logical_id: str) -> Dict[str, Any]:
        document = {
            "PolicyName": logical_id + "SNSPolicy",
            "PolicyDocument": {"Statement": [{"Action": "sns:publish", "Effect": "Allow", "Resource": topic_arn}]},
        }
        return document

    @classmethod
    def event_bus_put_events_role_policy(cls, event_bus_arn: Any, logical_id: str) -> Dict[str, Any]:
        document = {
            "PolicyName": logical_id + "EventBridgePolicy",
            "PolicyDocument": {
                "Statement": [{"Action": "events:PutEvents", "Effect": "Allow", "Resource": event_bus_arn}]
            },
        }
        return document

    @classmethod
    def lambda_invoke_function_role_policy(cls, function_arn: Any, logical_id: str) -> Dict[str, Any]:
        document = {
            "PolicyName": logical_id + "LambdaPolicy",
            "PolicyDocument": {
                "Statement": [{"Action": "lambda:InvokeFunction", "Effect": "Allow", "Resource": function_arn}]
            },
        }
        return document
