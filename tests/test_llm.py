"""Bedrock auth: API key bypasses the AWS login session."""

from __future__ import annotations

import json
import unittest
from io import BytesIO
from unittest.mock import patch

from llm import Bedrock


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> BytesIO:
        return BytesIO(self._payload)

    def __exit__(self, *args: object) -> None:
        return None


class BedrockApiKeyTests(unittest.TestCase):
    def test_uses_bearer_token_not_boto3(self) -> None:
        client = Bedrock()
        payload = {"output": {"message": {"content": [{"text": "tickets"}]}}}
        with (
            patch.dict(
                "os.environ",
                {"AWS_REGION": "us-east-1", "AWS_BEARER_TOKEN_BEDROCK": "test-key"},
                clear=False,
            ),
            patch("llm.boto3.client") as boto_client,
            patch("llm.urllib.request.urlopen", return_value=_Response(payload)) as urlopen,
        ):
            text = client.complete("extract")
        self.assertEqual(text, "tickets")
        boto_client.assert_not_called()
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertIn("bedrock-runtime.us-east-1.amazonaws.com", request.full_url)
        self.assertIn(client.model, request.full_url)
