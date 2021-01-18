import json
import re
import random
import string  # pylint: disable=deprecated-module

import boto3
from botocore.exceptions import ClientError, NoRegionError

from samtranslator.translator.logical_id_generator import LogicalIdGenerator

# Length of the random suffix added at the end of the resources we create
# to avoid collisions between tests
RANDOM_SUFFIX_LENGTH = 12


def verify_stack_resources(expected_file_path, stack_resources):
    """
    Verifies that the stack resources match the expected ones

    Parameters
    ----------
    expected_file_path : Path
        Path to the file containing the expected resources
    stack_resources : List
        Stack resources

    Returns
    -------
    bool
        True if the stack resources exactly match the expected ones, False otherwise
    """
    with open(expected_file_path) as expected_data:
        expected_resources = _sort_resources(json.load(expected_data))
    parsed_resources = _sort_resources(stack_resources["StackResourceSummaries"])

    if len(expected_resources) != len(parsed_resources):
        return False

    for i in range(len(expected_resources)):
        exp = expected_resources[i]
        parsed = parsed_resources[i]
        if not re.match(
            "^" + exp["LogicalResourceId"] + "([0-9a-f]{" + str(LogicalIdGenerator.HASH_LENGTH) + "})?$",
            parsed["LogicalResourceId"],
        ):
            return False
        if exp["ResourceType"] != parsed["ResourceType"]:
            return False
    return True


def generate_suffix():
    """
    Generates a basic random string of length RANDOM_SUFFIX_LENGTH
    to append to objects names used in the tests to avoid collisions
    between tests runs

    Returns
    -------
    string
        Random lowercase alphanumeric string of length RANDOM_SUFFIX_LENGTH
    """
    return "".join(random.choice(string.ascii_lowercase) for i in range(RANDOM_SUFFIX_LENGTH))


def _sort_resources(resources):
    """
    Sorts a stack's resources by LogicalResourceId

    Parameters
    ----------
    resources : list
        Resources to sort

    Returns
    -------
    list
        List of resources, sorted
    """
    if resources is None:
        return []
    return sorted(resources, key=lambda d: d["LogicalResourceId"])


def create_bucket(bucket_name, region):
    """
    Creates a S3 bucket in a specific region

    Parameters
    ----------
    bucket_name : string
        Bucket name
    region : string
        Region name

    Raises
    ------
    NoRegionError
        If region is not specified
    """
    if region is None:
        raise NoRegionError()
    if region == "us-east-1":
        s3_client = boto3.client("s3")
        s3_client.create_bucket(Bucket=bucket_name)
    else:
        s3_client = boto3.client("s3", region_name=region)
        location = {"LocationConstraint": region}
        s3_client.create_bucket(Bucket=bucket_name, CreateBucketConfiguration=location)
