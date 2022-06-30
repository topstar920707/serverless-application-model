import requests
from unittest.case import skipIf

from integration.helpers.base_test import BaseTest
from integration.helpers.resource import current_region_does_not_support
from integration.config.service_names import REST_API
from integration.helpers.deployer.utils.retry import retry
from parameterized import parameterized

from integration.helpers.exception import StatusCodeError

ALL_METHODS = "DELETE,GET,HEAD,OPTIONS,PATCH,POST,PUT"


@skipIf(current_region_does_not_support([REST_API]), "Rest API is not supported in this testing region")
class TestApiWithCors(BaseTest):
    @parameterized.expand(
        [
            "combination/api_with_cors",
            "combination/api_with_cors_openapi",
        ]
    )
    def test_cors(self, file_name):
        self.create_and_verify_stack(file_name)

        base_url = self.get_stack_outputs()["ApiUrl"]

        allow_methods = "methods"
        allow_origin = "origins"
        allow_headers = "headers"
        max_age = "600"

        self.verify_options_request(base_url + "/apione", allow_methods, allow_origin, allow_headers, max_age)
        self.verify_options_request(base_url + "/apitwo", allow_methods, allow_origin, allow_headers, max_age)

    def test_cors_with_shorthand_notation(self):
        self.create_and_verify_stack("combination/api_with_cors_shorthand")

        base_url = self.get_stack_outputs()["ApiUrl"]

        allow_origin = "origins"
        allow_headers = None  # This should be absent from response
        max_age = None  # This should be absent from response

        self.verify_options_request(base_url + "/apione", ALL_METHODS, allow_origin, allow_headers, max_age)
        self.verify_options_request(base_url + "/apitwo", "OPTIONS,POST", allow_origin, allow_headers, max_age)

    def test_cors_with_only_methods(self):
        self.create_and_verify_stack("combination/api_with_cors_only_methods")

        base_url = self.get_stack_outputs()["ApiUrl"]

        allow_methods = "methods"
        allow_origin = "*"
        allow_headers = None  # This should be absent from response
        max_age = None  # This should be absent from response

        self.verify_options_request(base_url + "/apione", allow_methods, allow_origin, allow_headers, max_age)
        self.verify_options_request(base_url + "/apitwo", allow_methods, allow_origin, allow_headers, max_age)

    def test_cors_with_only_headers(self):
        self.create_and_verify_stack("combination/api_with_cors_only_headers")

        base_url = self.get_stack_outputs()["ApiUrl"]

        allow_origin = "*"
        allow_headers = "headers"
        max_age = None  # This should be absent from response

        self.verify_options_request(base_url + "/apione", ALL_METHODS, allow_origin, allow_headers, max_age)
        self.verify_options_request(base_url + "/apitwo", "OPTIONS,POST", allow_origin, allow_headers, max_age)

    def test_cors_with_only_max_age(self):
        self.create_and_verify_stack("combination/api_with_cors_only_max_age")

        base_url = self.get_stack_outputs()["ApiUrl"]

        allow_origin = "*"
        allow_headers = None
        max_age = "600"

        self.verify_options_request(base_url + "/apione", ALL_METHODS, allow_origin, allow_headers, max_age)
        self.verify_options_request(base_url + "/apitwo", "OPTIONS,POST", allow_origin, allow_headers, max_age)

    @retry(StatusCodeError, 3)
    def verify_options_request(self, url, allow_methods, allow_origin, allow_headers, max_age):
        response = requests.options(url)
        status = response.status_code
        if status != 200:
            raise StatusCodeError("Request to {} failed with status: {}, expected status: 200".format(url, status))

        self.assertEqual(status, 200, "Options request must be successful and return HTTP 200")
        headers = response.headers
        self.assertEqual(
            headers.get("Access-Control-Allow-Methods"), allow_methods, "Allow-Methods header must have proper value"
        )
        self.assertEqual(
            headers.get("Access-Control-Allow-Origin"), allow_origin, "Allow-Origin header must have proper value"
        )
        self.assertEqual(
            headers.get("Access-Control-Allow-Headers"), allow_headers, "Allow-Headers header must have proper value"
        )
        self.assertEqual(headers.get("Access-Control-Max-Age"), max_age, "Max-Age header must have proper value")
