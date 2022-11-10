from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple, Union, cast

from samtranslator.metrics.method_decorator import cw_timer
from samtranslator.model import PropertyType, Resource, ResourceMacro
from samtranslator.model.iam import IAMRole
from samtranslator.model.sqs import SQSQueue
from samtranslator.model.types import is_str, is_type
from samtranslator.model.eventsources import FUNCTION_EVETSOURCE_METRIC_PREFIX
from samtranslator.model.eventbridge_utils import EventBridgeRuleUtils
from samtranslator.model.exceptions import InvalidEventException
from samtranslator.model.iam import IAMRolePolicies
from samtranslator.model.scheduler import SchedulerSchedule
from samtranslator.translator.logical_id_generator import LogicalIdGenerator


class _SchedulerScheduleTargetType(Enum):
    FUNCTION = auto()
    STATE_MACHINE = auto()


class SchedulerEventSource(ResourceMacro):
    """
    Scheduler event source for SAM Functions and SAM State Machine.

    It will translate into an "AWS::Scheduler::Schedule."
    Because a Scheduler Schedule resource requires an execution role,
    this macro will also create an IAM role with permissions to invoke
    the function/state machine.
    """

    resource_type = "ScheduleV2"

    # As the first version, the properties of Scheduler schedule event will be the
    # same as the original "Schedule" event.
    # See class "Schedule" in samtranslator.model.eventsources.push and samtranslator.model.stepfunctions.events.
    property_types = {
        "PermissionsBoundary": PropertyType(False, is_str()),
        "ScheduleExpression": PropertyType(True, is_str()),
        "FlexibleTimeWindow": PropertyType(False, is_type(dict)),
        "Name": PropertyType(False, is_str()),
        "State": PropertyType(False, is_str()),
        "Description": PropertyType(False, is_str()),
        "StartDate": PropertyType(False, is_str()),
        "EndDate": PropertyType(False, is_str()),
        "ScheduleExpressionTimezone": PropertyType(False, is_str()),
        "GroupName": PropertyType(False, is_str()),
        "KmsKeyArn": PropertyType(False, is_str()),
        "Input": PropertyType(False, is_str()),
        "RoleArn": PropertyType(False, is_str()),
        "DeadLetterConfig": PropertyType(False, is_type(dict)),
        "RetryPolicy": PropertyType(False, is_type(dict)),
    }

    # Below are type hints, must maintain consistent with properties_types
    # - pass-through to generated IAM role
    PermissionsBoundary: Optional[str]
    # - pass-through to AWS::Scheduler::Schedule
    ScheduleExpression: str
    FlexibleTimeWindow: Optional[Dict[str, Any]]
    Name: Optional[str]
    State: Optional[str]
    Description: Optional[str]
    StartDate: Optional[str]
    EndDate: Optional[str]
    ScheduleExpressionTimezone: Optional[str]
    GroupName: Optional[str]
    KmsKeyArn: Optional[str]
    # - pass-through to AWS::Scheduler::Schedule's Target
    Input: Optional[str]
    RoleArn: Optional[str]
    DeadLetterConfig: Optional[Dict[str, Any]]
    RetryPolicy: Optional[Dict[str, Any]]

    DEFAULT_FLEXIBLE_TIME_WINDOW = {"Mode": "OFF"}

    @cw_timer(prefix=FUNCTION_EVETSOURCE_METRIC_PREFIX)  # type: ignore
    def to_cloudformation(self, **kwargs: Dict[str, Any]) -> List[Resource]:
        """Returns the Scheduler Schedule and an IAM role.

        :param dict kwargs: no existing resources need to be modified
        :returns: a list of vanilla CloudFormation Resources, to which this push event expands
        :rtype: list
        """

        target: Resource

        # For SAM statemachine, the resource object is passed using kwargs["resource"],
        # https://github.com/aws/serverless-application-model/blob/a25933379e1cad3d0df4b35729ee2ec335402fdf/samtranslator/model/stepfunctions/generators.py#L266
        if kwargs.get("resource"):
            target_type = _SchedulerScheduleTargetType.STATE_MACHINE
            target = cast(Resource, kwargs["resource"])
        # for SAM function, the resource object is passed using kwargs["function"],
        # unlike SFN using "resource" keyword argument:
        # https://github.com/aws/serverless-application-model/blob/a25933379e1cad3d0df4b35729ee2ec335402fdf/samtranslator/model/sam_resources.py#L681
        elif kwargs.get("function"):
            target_type = _SchedulerScheduleTargetType.FUNCTION
            target = cast(Resource, kwargs["function"])
        else:
            raise TypeError("Missing required keyword argument: function/resource")

        passthrough_resource_attributes = target.get_passthrough_resource_attributes()  # type: ignore[no-untyped-call]

        resources: List[Resource] = []

        scheduler_schedule = self._construct_scheduler_schedule_without_target(passthrough_resource_attributes)
        resources.append(scheduler_schedule)

        dlq_queue_arn: Optional[str] = None
        if self.DeadLetterConfig is not None:
            # The dql config spec is the same as normal "Schedule" event,
            # so continue to use EventBridgeRuleUtils for validation.
            # However, Scheduler doesn't use AWS::SQS::QueuePolicy to grant permissions.
            # so we cannot use EventBridgeRuleUtils.get_dlq_queue_arn_and_resources() here.
            EventBridgeRuleUtils.validate_dlq_config(self.logical_id, self.DeadLetterConfig)  # type: ignore[no-untyped-call]
            dlq_queue_arn, dlq_resources = self._get_dlq_queue_arn_and_resources(
                self.DeadLetterConfig, passthrough_resource_attributes
            )
            resources.extend(dlq_resources)

        execution_role_arn: Union[str, Dict[str, Any]] = self.RoleArn  # type: ignore[assignment]
        if not execution_role_arn:
            execution_role = self._construct_execution_role(
                target, target_type, passthrough_resource_attributes, dlq_queue_arn, self.PermissionsBoundary
            )
            resources.append(execution_role)
            execution_role_arn = execution_role.get_runtime_attr("arn")  # type: ignore[no-untyped-call]

        scheduler_schedule.Target = self._construct_scheduler_schedule_target(target, execution_role_arn, dlq_queue_arn)

        return resources

    def _construct_scheduler_schedule_without_target(
        self, passthrough_resource_attributes: Dict[str, Any]
    ) -> SchedulerSchedule:
        scheduler_schedule = SchedulerSchedule(self.logical_id, attributes=passthrough_resource_attributes)
        scheduler_schedule.ScheduleExpression = self.ScheduleExpression

        if self.State:
            scheduler_schedule.State = self.State

        # Scheduler schedule's Name is a required property
        scheduler_schedule.Name = self.Name or self.logical_id

        # pass-through other properties
        scheduler_schedule.Description = self.Description
        scheduler_schedule.FlexibleTimeWindow = self.FlexibleTimeWindow or self.DEFAULT_FLEXIBLE_TIME_WINDOW
        scheduler_schedule.StartDate = self.StartDate
        scheduler_schedule.EndDate = self.EndDate
        scheduler_schedule.ScheduleExpressionTimezone = self.ScheduleExpressionTimezone
        scheduler_schedule.GroupName = self.GroupName
        scheduler_schedule.KmsKeyArn = self.KmsKeyArn

        return scheduler_schedule

    def _construct_execution_role(
        self,
        target: Resource,
        target_type: _SchedulerScheduleTargetType,
        passthrough_resource_attributes: Dict[str, Any],
        dlq_queue_arn: Optional[str],
        permissions_boundary: Optional[str],
    ) -> IAMRole:
        """Constructs the execution role for Scheduler Schedule."""
        if target_type == _SchedulerScheduleTargetType.FUNCTION:
            policy = IAMRolePolicies.lambda_invoke_function_role_policy(target.get_runtime_attr("arn"), self.logical_id)  # type: ignore[no-untyped-call, no-untyped-call]
        elif target_type == _SchedulerScheduleTargetType.STATE_MACHINE:
            policy = IAMRolePolicies.step_functions_start_execution_role_policy(  # type: ignore[no-untyped-call]
                target.get_runtime_attr("arn"), self.logical_id  # type: ignore[no-untyped-call]
            )
        else:
            raise RuntimeError(f"Unexpected target type {target_type.name}")

        role_logical_id = LogicalIdGenerator(self.logical_id + "Role").gen()  # type: ignore[no-untyped-call, no-untyped-call]
        execution_role = IAMRole(role_logical_id, attributes=passthrough_resource_attributes)
        execution_role.AssumeRolePolicyDocument = IAMRolePolicies.scheduler_assume_role_policy()

        policies = [policy]
        if dlq_queue_arn:
            policies.append(IAMRolePolicies.sqs_send_message_role_policy(dlq_queue_arn, self.logical_id))
        execution_role.Policies = policies

        if permissions_boundary:
            execution_role.PermissionsBoundary = permissions_boundary
        return execution_role

    def _construct_scheduler_schedule_target(
        self, target: Resource, execution_role_arn: Union[str, Dict[str, Any]], dead_letter_queue_arn: Optional[Any]
    ) -> Dict[str, Any]:
        """Constructs the Target property for the Scheduler Schedule.

        :returns: the Target property
        :rtype: dict

        Inspired by https://github.com/aws/serverless-application-model/blob/a25933379e1cad3d0df4b35729ee2ec335402fdf/samtranslator/model/eventsources/push.py#L157
        """
        target_dict: Dict[str, Any] = {
            "Arn": target.get_runtime_attr("arn"),  # type: ignore[no-untyped-call]
            "RoleArn": execution_role_arn,
        }
        if self.Input is not None:
            target_dict["Input"] = self.Input

        if self.DeadLetterConfig is not None:
            target_dict["DeadLetterConfig"] = {"Arn": dead_letter_queue_arn}

        if self.RetryPolicy is not None:
            target_dict["RetryPolicy"] = self.RetryPolicy

        return target_dict

    def _get_dlq_queue_arn_and_resources(
        self, dlq_config: Dict[str, Any], passthrough_resource_attributes: Optional[Dict[str, Any]]
    ) -> Tuple[Any, List[Resource]]:
        """
        Returns dlq queue arn and dlq_resources, assuming self.DeadLetterConfig has been validated.

        Inspired by https://github.com/aws/serverless-application-model/blob/a25933379e1cad3d0df4b35729ee2ec335402fdf/samtranslator/model/eventbridge_utils.py#L44
        """
        dlq_queue_arn = dlq_config.get("Arn")
        if dlq_queue_arn is not None:
            return dlq_queue_arn, []
        queue_logical_id = dlq_config.get("QueueLogicalId")
        if queue_logical_id is not None and not isinstance(queue_logical_id, str):
            raise InvalidEventException(
                self.logical_id,
                "QueueLogicalId must be a string",
            )
        dlq_resources: List[Resource] = []
        queue = SQSQueue(queue_logical_id or self.logical_id + "Queue", attributes=passthrough_resource_attributes)
        dlq_resources.append(queue)

        dlq_queue_arn = queue.get_runtime_attr("arn")  # type: ignore[no-untyped-call]
        return dlq_queue_arn, dlq_resources
