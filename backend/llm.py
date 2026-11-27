"""Model clients. The parser uses Ollama, then Bedrock. Solve and verify use Cursor."""

from __future__ import annotations

import json
import os
import urllib.request

import boto3
from botocore.config import Config

from config import load_local_env, product_cwd, require_env, require_env_int

load_local_env()

SUMMARY_MODEL = require_env("FLEETAI_SUMMARY_MODEL")
ADDITIONAL_CONTEXT_SUMMARY_CHARS = require_env_int("FLEETAI_SUMMARY_LIMIT")
OLLAMA_URL = require_env("OLLAMA_HOST").rstrip("/")
OLLAMA_TIMEOUT = require_env_int("FLEETAI_OLLAMA_TIMEOUT")
OLLAMA_MAX_TOKENS = require_env_int("FLEETAI_OLLAMA_MAX_TOKENS")
OLLAMA_CONTEXT_WINDOW = require_env_int("FLEETAI_OLLAMA_CONTEXT_WINDOW")
BEDROCK_MODEL = require_env("BEDROCK_MODEL_ID")
BEDROCK_MAX_TOKENS = require_env_int("FLEETAI_BEDROCK_MAX_TOKENS")
BEDROCK_TIMEOUT = require_env_int("FLEETAI_BEDROCK_TIMEOUT")
BEDROCK_CONNECT_TIMEOUT = require_env_int("FLEETAI_BEDROCK_CONNECT_TIMEOUT")
CURSOR_MODEL = require_env("FLEETAI_CURSOR_MODEL")
CURSOR_REASONING = require_env("FLEETAI_CURSOR_REASONING")
CURSOR_FAST = require_env("FLEETAI_CURSOR_FAST")


class Ollama:
    """Local summarizer. A short document is returned unchanged."""

    def __init__(self, model: str = SUMMARY_MODEL, url: str = OLLAMA_URL) -> None:
        self.model = model
        self.url = url

    def summarize(self, text: str, limit: int = ADDITIONAL_CONTEXT_SUMMARY_CHARS) -> str:
        text = text.strip()
        if len(text) <= limit:
            return text
        instruction = (
            "Summarize this evidence for a ticket extractor. "
            "Stay within {0} characters. ".format(limit)
            + "Keep every defect id, case id, session id, code, what was shown, "
            "what was stored, and the required outcome. "
            "Drop the review method, questions, passed checks, and plans for a later round. "
            "Plain text only. No preamble.\n\n"
            + text
        )
        payload = json.dumps({
            "model": self.model,
            "stream": False,
            "think": False,
            "messages": [
                {"role": "user", "content": instruction},
                {"role": "assistant", "content": "\n"},
            ],
            "options": {"temperature": 0, "num_predict": OLLAMA_MAX_TOKENS, "num_ctx": OLLAMA_CONTEXT_WINDOW},
        }).encode("utf-8")
        request = urllib.request.Request(
            self.url + "/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT) as response:
            body = json.load(response)
        summary = str(body["message"].get("content") or "").strip()
        if not summary:
            raise RuntimeError("local summary was empty ({0})".format(body.get("done_reason") or "no reason"))
        if len(summary) > limit:
            summary = summary[:limit].rsplit("\n", 1)[0].strip()
        return summary


class Bedrock:
    """Ticket extractor."""

    def __init__(self, model: str = BEDROCK_MODEL) -> None:
        self.model = model

    def complete(self, prompt: str) -> str:
        region = require_env("AWS_REGION")
        messages = [{"role": "user", "content": [{"text": prompt}]}]
        inference = {"temperature": 0, "maxTokens": BEDROCK_MAX_TOKENS}
        api_key = (os.getenv("AWS_BEARER_TOKEN_BEDROCK") or os.getenv("BEDROCK_API_KEY") or "").strip()
        if api_key:
            return self._complete_with_api_key(region, api_key, messages, inference)
        reply = boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=Config(read_timeout=BEDROCK_TIMEOUT, connect_timeout=BEDROCK_CONNECT_TIMEOUT, retries={"max_attempts": 2}),
        ).converse(
            modelId=self.model,
            messages=messages,
            inferenceConfig=inference,
        )
        return reply["output"]["message"]["content"][0]["text"].strip()

    def _complete_with_api_key(self, region: str, api_key: str, messages: list, inference: dict) -> str:
        payload = json.dumps({"messages": messages, "inferenceConfig": inference}).encode("utf-8")
        request = urllib.request.Request(
            "https://bedrock-runtime.{0}.amazonaws.com/model/{1}/converse".format(region, self.model),
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer {0}".format(api_key),
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=BEDROCK_TIMEOUT) as response:
            reply = json.load(response)
        return reply["output"]["message"]["content"][0]["text"].strip()


class Cursor:
    """Solver and verifier. Runs in the product checkout."""

    def __init__(self, model: str = CURSOR_MODEL) -> None:
        self.model = model

    def run(self, prompt: str, images: list[tuple[str, bytes]] | None = None):
        api_key = require_env("CURSOR_API_KEY")
        from cursor_sdk import Agent, AgentOptions, LocalAgentOptions, ModelParameterValue, ModelSelection, SDKImage, UserMessage

        model = self.model
        if self.model.startswith("grok-"):
            model = ModelSelection(
                id=self.model,
                params=[
                    ModelParameterValue(id="reasoning", value=CURSOR_REASONING),
                    ModelParameterValue(id="fast", value=CURSOR_FAST),
                ],
            )
        message: str | UserMessage = prompt
        if images:
            message = UserMessage(
                text=prompt,
                images=[SDKImage.from_data(data, "image/" + fmt) for fmt, data in images],
            )
        database_url = os.environ.pop("DATABASE_URL", None)
        try:
            result = Agent.prompt(
                message,
                AgentOptions(api_key=api_key, model=model, local=LocalAgentOptions(cwd=str(product_cwd()))),
            )
        finally:
            if database_url is not None:
                os.environ["DATABASE_URL"] = database_url
        if result.status == "error":
            raise RuntimeError("run failed: {0}".format(result.id))
        return result


ollama = Ollama()
bedrock = Bedrock()
cursor = Cursor()
