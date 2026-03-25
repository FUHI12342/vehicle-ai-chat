import asyncio
import json
import logging

import boto3

from app.llm.base import LLMProvider, LLMResponse, EmbeddingResponse

logger = logging.getLogger(__name__)

BEDROCK_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
BEDROCK_REGION = "us-east-1"


class BedrockProvider(LLMProvider):
    name = "bedrock"
    display_name = "AWS Bedrock (Claude)"

    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=BEDROCK_REGION,
            )
        return self._client

    def is_configured(self) -> bool:
        try:
            session = boto3.Session()
            creds = session.get_credentials()
            return creds is not None
        except Exception:
            return False

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        json_mode: bool = False,
        response_format: dict | None = None,
    ) -> LLMResponse:
        client = self._get_client()

        # Separate system messages from conversation
        system_parts: list[str] = []
        converse_messages: list[dict] = []

        for msg in messages:
            role = msg["role"]
            content = msg.get("content", "")
            if role == "system":
                system_parts.append(content)
            elif role in ("user", "assistant"):
                converse_messages.append({
                    "role": role,
                    "content": [{"text": content}],
                })

        # Merge consecutive same-role messages (Bedrock requires alternating)
        converse_messages = _merge_consecutive(converse_messages)

        # Ensure first message is user (Bedrock requirement)
        if converse_messages and converse_messages[0]["role"] != "user":
            converse_messages.insert(0, {
                "role": "user",
                "content": [{"text": "続けてください"}],
            })

        # Add JSON schema instructions to system prompt
        if response_format and response_format.get("type") == "json_schema":
            schema_info = response_format.get("json_schema", {})
            schema = schema_info.get("schema", {})
            schema_instruction = (
                "\n\n# 出力フォーマット（厳守）\n"
                "以下のJSONスキーマに厳密に従い、JSONのみを出力してください。\n"
                "JSON以外のテキスト（説明、マークダウン、コードフェンス）は一切含めないでください。\n"
                f"{json.dumps(schema, ensure_ascii=False)}"
            )
            system_parts.append(schema_instruction)
        elif json_mode:
            system_parts.append(
                "\n\n# 出力フォーマット（厳守）\n"
                "JSON形式のみで回答してください。JSON以外のテキストは一切含めないでください。"
            )

        kwargs: dict = {
            "modelId": BEDROCK_MODEL_ID,
            "messages": converse_messages,
            "inferenceConfig": {
                "temperature": temperature,
                "maxTokens": max_tokens,
            },
        }
        if system_parts:
            kwargs["system"] = [{"text": "\n\n".join(system_parts)}]

        loop = asyncio.get_event_loop()
        response = await _converse_with_retry(loop, client, kwargs)

        # Extract content
        content_blocks = (
            response.get("output", {}).get("message", {}).get("content", [])
        )
        content = "".join(b.get("text", "") for b in content_blocks)
        stop_reason = response.get("stopReason", "unknown")
        usage_data_log = response.get("usage", {})
        logger.info(
            "Bedrock response: stopReason=%s len=%d in=%d out=%d",
            stop_reason, len(content),
            usage_data_log.get("inputTokens", 0),
            usage_data_log.get("outputTokens", 0),
        )
        if len(content) < 10:
            logger.warning("Bedrock very short response: '%s'", content)

        # Strip markdown code fences if present
        content = _strip_code_fences(content)

        usage_data = response.get("usage", {})
        return LLMResponse(
            content=content,
            usage={
                "prompt_tokens": usage_data.get("inputTokens", 0),
                "completion_tokens": usage_data.get("outputTokens", 0),
            },
        )

    async def embed(self, texts: list[str]) -> EmbeddingResponse:
        raise NotImplementedError(
            "Use local embedding provider instead of Bedrock"
        )

    async def health_check(self) -> bool:
        if not self.is_configured():
            return False
        try:
            client = self._get_client()
            client.converse(
                modelId=BEDROCK_MODEL_ID,
                messages=[{
                    "role": "user",
                    "content": [{"text": "ok"}],
                }],
                inferenceConfig={"maxTokens": 5},
            )
            return True
        except Exception as e:
            logger.warning(f"Bedrock health check failed: {e}")
            return False


async def _converse_with_retry(loop, client, kwargs, max_retries: int = 5):
    """Retry Bedrock converse with exponential backoff for throttling."""
    from botocore.exceptions import ClientError
    for attempt in range(max_retries):
        try:
            return await loop.run_in_executor(
                None, lambda: client.converse(**kwargs)
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ThrottlingException":
                wait = 1.0 * (2 ** attempt)
                logger.warning(
                    "Bedrock throttled (attempt %d/%d), retrying in %.1fs",
                    attempt + 1, max_retries, wait,
                )
                await asyncio.sleep(wait)
            else:
                raise
    # Final attempt without catch
    return await loop.run_in_executor(
        None, lambda: client.converse(**kwargs)
    )


def _merge_consecutive(messages: list[dict]) -> list[dict]:
    """Merge consecutive messages with the same role."""
    if not messages:
        return []
    merged: list[dict] = [messages[0]]
    for msg in messages[1:]:
        if msg["role"] == merged[-1]["role"]:
            merged[-1]["content"].extend(msg["content"])
        else:
            merged.append(msg)
    return merged


def _strip_code_fences(text: str) -> str:
    """Remove ```json ... ``` wrappers if present."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        # Remove first line (```json) and last line (```)
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        stripped = "\n".join(lines).strip()
    return stripped
