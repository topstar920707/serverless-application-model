from unittest.mock import Mock, patch
from unittest import TestCase

from samtranslator.model.eventsources.push import EventBridgeRule
from samtranslator.model.lambda_ import LambdaFunction
from samtranslator.model.exceptions import InvalidEventException


class EventBridgeRuleSourceTests(TestCase):
    def setUp(self):
        self.logical_id = "EventBridgeRule"
        self.func = LambdaFunction("func")

        self.eb_event_source = EventBridgeRule(self.logical_id)
        self.eb_event_source.Pattern = {"detail": {"state": ["terminated"]}}

    def test_target_id_when_not_provided(self):
        cfn = self.eb_event_source.to_cloudformation(function=self.func)
        target_id = cfn[0].Targets[0]["Id"]
        self.assertEqual(target_id, "{}{}".format(self.logical_id, "LambdaTarget"))

    def test_target_id_when_provided(self):
        self.eb_event_source.Target = {"Id": "MyTargetId"}
        cfn = self.eb_event_source.to_cloudformation(function=self.func)
        target_id = cfn[0].Targets[0]["Id"]
        self.assertEqual(target_id, "MyTargetId")

    def test_to_cloudformation_with_retry_policy(self):
        retry_policy = {"MaximumRetryAttempts": "10", "MaximumEventAgeInSeconds": "300"}
        self.eb_event_source.RetryPolicy = retry_policy
        resources = self.eb_event_source.to_cloudformation(function=self.func)
        self.assertEqual(len(resources), 2)
        event_rule = resources[0]
        self.assertEqual(event_rule.Targets[0]["RetryPolicy"], retry_policy)

    def test_to_cloudformation_with_dlq_arn_provided(self):
        dead_letter_config = {"Arn": "DeadLetterQueueArn"}
        self.eb_event_source.DeadLetterConfig = dead_letter_config
        resources = self.eb_event_source.to_cloudformation(function=self.func)
        self.assertEqual(len(resources), 2)
        event_rule = resources[0]
        self.assertEqual(event_rule.Targets[0]["DeadLetterConfig"], dead_letter_config)

    def test_to_cloudformation_invalid_both_dlq_arn_and_type_provided(self):
        dead_letter_config = {"Arn": "DeadLetterQueueArn", "Type": "SQS"}
        self.eb_event_source.DeadLetterConfig = dead_letter_config
        with self.assertRaises(InvalidEventException):
            self.eb_event_source.to_cloudformation(function=self.func)

    def test_to_cloudformation_invalid_dlq_type_provided(self):
        dead_letter_config = {"Type": "SNS", "QueueLogicalId": "MyDLQ"}
        self.eb_event_source.DeadLetterConfig = dead_letter_config
        with self.assertRaises(InvalidEventException):
            self.eb_event_source.to_cloudformation(function=self.func)

    def test_to_cloudformation_missing_dlq_type_or_arn(self):
        dead_letter_config = {"QueueLogicalId": "MyDLQ"}
        self.eb_event_source.DeadLetterConfig = dead_letter_config
        with self.assertRaises(InvalidEventException):
            self.eb_event_source.to_cloudformation(function=self.func)

    def test_to_cloudformation_with_dlq_generated(self):
        dead_letter_config = {"Type": "SQS"}
        dead_letter_config_translated = {"Arn": {"Fn::GetAtt": [self.logical_id + "Queue", "Arn"]}}
        self.eb_event_source.DeadLetterConfig = dead_letter_config
        resources = self.eb_event_source.to_cloudformation(function=self.func)
        self.assertEqual(len(resources), 4)
        event_rule = resources[2]
        self.assertEqual(event_rule.Targets[0]["DeadLetterConfig"], dead_letter_config_translated)

    def test_to_cloudformation_with_dlq_generated_with_custom_logical_id(self):
        dead_letter_config = {"Type": "SQS", "QueueLogicalId": "MyDLQ"}
        dead_letter_config_translated = {"Arn": {"Fn::GetAtt": ["MyDLQ", "Arn"]}}
        self.eb_event_source.DeadLetterConfig = dead_letter_config
        resources = self.eb_event_source.to_cloudformation(function=self.func)
        self.assertEqual(len(resources), 4)
        event_rule = resources[2]
        self.assertEqual(event_rule.Targets[0]["DeadLetterConfig"], dead_letter_config_translated)

    def test_to_cloudformation_with_dlq_generated_with_intrinsic_function_custom_logical_id_raises_exception(self):
        dead_letter_config = {"Type": "SQS", "QueueLogicalId": {"Fn::Sub": "MyDLQ${Env}"}}
        self.eb_event_source.DeadLetterConfig = dead_letter_config
        with self.assertRaises(InvalidEventException):
            self.eb_event_source.to_cloudformation(function=self.func)
