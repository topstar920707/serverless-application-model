import logging

from samtranslator.metrics.method_decorator import cw_timer

LOG = logging.getLogger(__name__)


class ManagedPolicyLoader(object):
    def __init__(self, iam_client):  # type: ignore[no-untyped-def]
        self._iam_client = iam_client
        self._policy_map = None
        self.max_items = 1000

    @cw_timer(prefix="External", name="IAM")  # type: ignore[no-untyped-call]
    def _load_policies_from_iam(self):  # type: ignore[no-untyped-def]
        LOG.info("Loading policies from IAM...")

        paginator = self._iam_client.get_paginator("list_policies")
        # Setting the scope to AWS limits the returned values to only AWS Managed Policies and will
        # not returned policies owned by any specific account.
        # http://docs.aws.amazon.com/IAM/latest/APIReference/API_ListPolicies.html#API_ListPolicies_RequestParameters
        # Note(jfuss): boto3 PaginationConfig MaxItems does not control the number of items returned from the API
        # call. This is actually controlled by PageSize.
        page_iterator = paginator.paginate(Scope="AWS", PaginationConfig={"PageSize": self.max_items})
        name_to_arn_map = {}  # type: ignore[var-annotated]

        for page in page_iterator:
            name_to_arn_map.update(map(lambda x: (x["PolicyName"], x["Arn"]), page["Policies"]))

        LOG.info("Finished loading policies from IAM.")
        self._policy_map = name_to_arn_map

    def load(self):  # type: ignore[no-untyped-def]
        if self._policy_map is None:
            self._load_policies_from_iam()
        return self._policy_map
