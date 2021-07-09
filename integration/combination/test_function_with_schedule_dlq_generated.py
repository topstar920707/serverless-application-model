from integration.helpers.base_test import BaseTest
from integration.helpers.common_api import get_queue_policy


class TestFunctionWithScheduleDlqGenerated(BaseTest):
    def test_function_with_schedule(self):
        self.create_and_verify_stack("combination/function_with_schedule_dlq_generated")

        stack_outputs = self.get_stack_outputs()

        schedule_name = stack_outputs["ScheduleName"]
        lambda_target_arn = stack_outputs["MyLambdaArn"]
        lambda_target_dlq_arn = stack_outputs["MyDLQArn"]
        lambda_target_dlq_url = stack_outputs["MyDLQUrl"]

        cloud_watch_events_client = self.client_provider.cloudwatch_event_client
        sqs_client = self.client_provider.sqs_client

        # get the cloudwatch schedule rule
        cw_rule_result = cloud_watch_events_client.describe_rule(Name=schedule_name)

        # checking if the name, description and state properties are correct
        self.assertEqual(cw_rule_result["Name"], schedule_name)
        self.assertEqual(cw_rule_result["Description"], "test schedule")
        self.assertEqual(cw_rule_result["State"], "ENABLED")
        self.assertEqual(cw_rule_result["ScheduleExpression"], "rate(5 minutes)")

        # checking if the target has a dead-letter queue attached to it
        targets = cloud_watch_events_client.list_targets_by_rule(Rule=schedule_name)["Targets"]

        self.assertEqual(len(targets), 1, "Rule should contain a single target")
        target = targets[0]

        self.assertEqual(target["Arn"], lambda_target_arn)
        self.assertEqual(target["DeadLetterConfig"]["Arn"], lambda_target_dlq_arn)

        # checking if the generated dead-letter queue has necessary resource based policy attached to it
        dlq_policy = get_queue_policy(lambda_target_dlq_url, sqs_client)
        self.assertEqual(len(dlq_policy), 1, "Only one statement must be in Dead-letter queue policy")
        dlq_policy_statement = dlq_policy[0]

        # checking policy action
        self.assertFalse(
            isinstance(dlq_policy_statement["Action"], list), "Only one action must be in dead-letter queue policy"
        )  # if it is an array, it means has more than one action
        self.assertEqual(
            dlq_policy_statement["Action"],
            "sqs:SendMessage",
            "Action referenced in dead-letter queue policy must be 'sqs:SendMessage'",
        )

        # checking service principal
        self.assertEqual(
            len(dlq_policy_statement["Principal"]),
            1,
        )
        self.assertEqual(
            dlq_policy_statement["Principal"]["Service"],
            "events.amazonaws.com",
            "Policy should grant EventBridge service principal to send messages to dead-letter queue",
        )

        # checking condition type
        key, value = get_first_key_value_pair_in_dict(dlq_policy_statement["Condition"])
        self.assertEqual(key, "ArnEquals")

        # checking condition key
        self.assertEqual(len(dlq_policy_statement["Condition"]), 1)
        condition_kay, condition_value = get_first_key_value_pair_in_dict(value)
        self.assertEqual(condition_kay, "aws:SourceArn")

        # checking condition value
        self.assertEqual(len(dlq_policy_statement["Condition"][key]), 1)
        self.assertEqual(
            condition_value,
            cw_rule_result["Arn"],
            "Policy should only allow requests coming from schedule rule resource",
        )


def get_first_key_value_pair_in_dict(dictionary):
    key = list(dictionary.keys())[0]
    value = dictionary[key]
    return key, value
