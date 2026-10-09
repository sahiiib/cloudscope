import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, ReadTimeoutError
from Tea.exceptions import TeaException

from cloudscope.collector.errors import describe_error


@pytest.mark.parametrize(
    "exc, expected",
    [
        (
            ClientError(
                {"Error": {"Code": "UnauthorizedOperation", "Message": "fake-secret"}}, "Scan"
            ),
            "UnauthorizedOperation",
        ),
        (TeaException({"code": "Forbidden.RAM", "message": "fake-secret"}), "Forbidden.RAM"),
        (
            EndpointConnectionError(endpoint_url="https://placeholder.invalid/fake-secret"),
            "EndpointConnectionError",
        ),
        (
            ReadTimeoutError(endpoint_url="https://placeholder.invalid/fake-secret"),
            "ReadTimeoutError",
        ),
        (TimeoutError("fake-secret"), "TimeoutError"),
        (RuntimeError("fake-secret"), "RuntimeError"),
        (TeaException({"message": "fake-secret"}), "TeaException"),
        (
            ClientError({"Error": {"Code": "invalid\ncode", "Message": "fake-secret"}}, "Scan"),
            "ClientError",
        ),
        (TeaException({"code": "A" * 300}), "A" * 160),
    ],
)
def test_describe_error_exposes_only_identifier(exc: Exception, expected: str) -> None:
    assert describe_error(exc) == expected
