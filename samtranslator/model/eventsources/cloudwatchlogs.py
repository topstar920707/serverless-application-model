from samtranslator.metrics.method_decorator import cw_timer
from samtranslator.model import PropertyType
from samtranslator.model.intrinsics import fnSub
from samtranslator.model.log import SubscriptionFilter
from samtranslator.model.types import is_str
from samtranslator.translator.arn_generator import ArnGenerator
from . import FUNCTION_EVETSOURCE_METRIC_PREFIX
from .push import PushEventSource


class CloudWatchLogs(PushEventSource):
    """CloudWatch Logs event source for SAM Functions."""

    resource_type = "CloudWatchLogs"
    principal = "logs.amazonaws.com"
    property_types = {"LogGroupName": PropertyType(True, is_str()), "FilterPattern": PropertyType(True, is_str())}

    @cw_timer(prefix=FUNCTION_EVETSOURCE_METRIC_PREFIX)  # type: ignore[no-untyped-call]
    def to_cloudformation(self, **kwargs):  # type: ignore[no-untyped-def]
        """Returns the CloudWatch Logs Subscription Filter and Lambda Permission to which this CloudWatch Logs event source
        corresponds.

        :param dict kwargs: no existing resources need to be modified
        :returns: a list of vanilla CloudFormation Resources, to which this push event expands
        :rtype: list
        """
        function = kwargs.get("function")

        if not function:
            raise TypeError("Missing required keyword argument: function")

        source_arn = self.get_source_arn()  # type: ignore[no-untyped-call]
        permission = self._construct_permission(function, source_arn=source_arn)  # type: ignore[no-untyped-call]
        subscription_filter = self.get_subscription_filter(function, permission)  # type: ignore[no-untyped-call]
        resources = [permission, subscription_filter]

        return resources

    def get_source_arn(self):  # type: ignore[no-untyped-def]
        resource = "log-group:${__LogGroupName__}:*"
        partition = ArnGenerator.get_partition_name()  # type: ignore[no-untyped-call]

        return fnSub(
            ArnGenerator.generate_arn(partition=partition, service="logs", resource=resource),  # type: ignore[no-untyped-call]
            {"__LogGroupName__": self.LogGroupName},  # type: ignore[attr-defined]
        )

    def get_subscription_filter(self, function, permission):  # type: ignore[no-untyped-def]
        subscription_filter = SubscriptionFilter(
            self.logical_id,
            depends_on=[permission.logical_id],
            attributes=function.get_passthrough_resource_attributes(),
        )
        subscription_filter.LogGroupName = self.LogGroupName  # type: ignore[attr-defined]
        subscription_filter.FilterPattern = self.FilterPattern  # type: ignore[attr-defined]
        subscription_filter.DestinationArn = function.get_runtime_attr("arn")

        return subscription_filter
