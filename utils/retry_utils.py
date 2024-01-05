import grpc
import requests

import google.api_core.exceptions
import openai.error

RETRYABLE_EXCEPTIONS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    google.api_core.exceptions.DeadlineExceeded,
    google.api_core.exceptions.InternalServerError,
    google.api_core.exceptions.ServiceUnavailable,
    google.api_core.exceptions.ResourceExhausted,
    grpc.aio._call.AioRpcError,
    openai.error.APIConnectionError,
    openai.error.RateLimitError,
    openai.error.APIError,
    openai.error.ServiceUnavailableError,
    openai.error.InvalidRequestError,
    ValueError,
)

OPENAI_RETRYABLE_EXCEPTIONS = (
    openai.error.APIConnectionError,
    openai.error.RateLimitError,
    openai.error.APIError,
    openai.error.ServiceUnavailableError,
)
