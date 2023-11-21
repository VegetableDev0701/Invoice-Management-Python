import logging
import sys

import openai
import tiktoken
from tenacity import (
    retry_if_exception_type,
    wait_exponential_jitter,
    stop_after_attempt,
    AsyncRetrying,
    RetryError,
    before_sleep_log,
)

from utils.retry_utils import OPENAI_RETRYABLE_EXCEPTIONS
from global_vars.globals_io import RETRY_TIMES

# Create a logger

num_tokens_logger = logging.getLogger("num_tokens")
num_tokens_logger.setLevel(logging.DEBUG)

gpt_logger = logging.getLogger("error_logger")
gpt_logger.setLevel(logging.DEBUG)

# Create a file handler
# handler = logging.FileHandler(
#     "/Users/mgrant/STAK/app/stak-backend/api/logs/gpt_model_errors.log"
# )
# handler_num_tokens = logging.FileHandler(
#     "/Users/mgrant/STAK/app/stak-backend/api/logs/gpt_token_count.log"
# )

handler_num_tokens = logging.StreamHandler(sys.stdout)
handler_num_tokens.setLevel(logging.INFO)

handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)

# Create a logging format
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
handler_num_tokens.setFormatter(formatter)

# Add the handlers to the logger
gpt_logger.addHandler(handler)
num_tokens_logger.addHandler(handler_num_tokens)


async def get_completion_gpt4(
    messages: str,
    max_tokens: int,
    model: str = "gpt-4",
    temperature: float = 0.3,
    job_type: str | None = None,
):
    num_tokens = num_tokens_from_messages(messages=messages)
    num_tokens_logger.info(f"Job: {job_type}; Input tokens: {num_tokens}")
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(),
            retry=retry_if_exception_type(OPENAI_RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(gpt_logger, logging.DEBUG),
        ):
            with attempt:
                messages = [{"role": "user", "content": messages}]
                try:
                    response = await openai.ChatCompletion.acreate(
                        model=model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    num_tokens = num_tokens_from_messages(
                        messages=response.choices[0].message["content"]
                    )
                    num_tokens_logger.info(
                        f"Job: {job_type}; Ouput tokens: {num_tokens}"
                    )
                    # num_tokens_logger.info("-" * 60)
                    return response.choices[0].message["content"]
                except Exception as e:
                    print(e)
                    return None
    except RetryError as e:
        print("retrying....")
        gpt_logger.error(f"{e} occured while requesting from GPT4 model.")
        raise
    except Exception as e:
        gpt_logger.exception(
            f"Unexpected error occured while requesting from GPT4 model.: {e}"
        )
        raise


async def get_completion_gpt35(
    messages: str,
    max_tokens: int,
    model: str = "gpt-3.5-turbo-16k",
    temperature: float = 0.3,
    job_type: str | None = None,
):
    num_tokens = num_tokens_from_messages(messages=messages)
    num_tokens_logger.info(f"Job: {job_type}; Input tokens: {num_tokens}")
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(),
            retry=retry_if_exception_type(OPENAI_RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(gpt_logger, logging.DEBUG),
        ):
            with attempt:
                messages = [{"role": "user", "content": messages}]
                response = await openai.ChatCompletion.acreate(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                num_tokens = num_tokens_from_messages(
                    messages=response.choices[0].message["content"]
                )
                num_tokens_logger.info(f"Job: {job_type}; Output tokens: {num_tokens}")
                return response.choices[0].message["content"]
    except RetryError as e:
        gpt_logger.error(f"{e} occured while requesting from GPT3.5 model.")
        raise
    except Exception as e:
        gpt_logger.exception(
            f"Unexpected error occured while requesting from GPT3.5 model.: {e}"
        )
        raise


def num_tokens_from_messages(messages, model="gpt-3.5-turbo"):
    messages = [{"role": "user", "content": messages}]
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    if model == "gpt-3.5-turbo":  # note: future models may deviate from this
        num_tokens = 0
        for message in messages:
            num_tokens += (
                4  # every message follows <im_start>{role/name}\n{content}<im_end>\n
            )
            for key, value in message.items():
                num_tokens += len(encoding.encode(value))
                if key == "name":  # if there's a name, the role is omitted
                    num_tokens += -1  # role is always required and always 1 token
        num_tokens += 2  # every reply is primed with <im_start>assistant
        return num_tokens
    else:
        raise NotImplementedError(
            f"""num_tokens_from_messages() is not presently implemented for model {model}.
  See https://github.com/openai/openai-python/blob/main/chatml.md for information on how messages are converted to tokens."""
        )
