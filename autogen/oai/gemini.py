"""OpenAI-compatible client for Google Gemini API (google-genai SDK).

Supports two backends — auto-selected based on config:

  AI Studio (api_key):
    llm_config={"config_list": [{"api_type": "google", "model": "gemini-2.0-flash",
                                  "api_key": "AIza..."}]}

  Vertex AI (uses $300 GCP free credit, no api_key needed):
    llm_config={"config_list": [{"api_type": "google", "model": "gemini-2.0-flash",
                                  "project": "my-gcp-project", "location": "us-central1"}]}
    Auth: run `gcloud auth application-default login` first.

Install: pip install google-genai google-cloud-aiplatform
"""

from __future__ import annotations

import json
import os
import random
import time
import warnings
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types
from google.genai.errors import ClientError
from openai.types.chat import ChatCompletion
from openai.types.chat.chat_completion import ChatCompletionMessage, Choice
from openai.types.chat.chat_completion_message_tool_call import ChatCompletionMessageToolCall, Function
from openai.types.completion_usage import CompletionUsage


GEMINI_PRICING = {
    "gemini-2.0-flash":      {"input": 0.10,  "output": 0.40},
    "gemini-2.0-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini-1.5-flash":      {"input": 0.075, "output": 0.30},
    "gemini-1.5-pro":        {"input": 1.25,  "output": 5.00},
    "gemini-1.0-pro":        {"input": 0.50,  "output": 1.50},
}


def calculate_gemini_cost(input_tokens: int, output_tokens: int, model: str) -> float:
    for key, price in GEMINI_PRICING.items():
        if key in model:
            return price["input"] * input_tokens / 1e6 + price["output"] * output_tokens / 1e6
    warnings.warn(f"Cost not implemented for {model}, using gemini-2.0-flash pricing.", UserWarning)
    return 0.10 * input_tokens / 1e6 + 0.40 * output_tokens / 1e6


def oai_tools_to_gemini_tools(tools: List[Dict]) -> List[types.Tool]:
    """Convert OpenAI tool definitions to Gemini Tool format."""
    declarations = []
    for tool in tools:
        if tool.get("type") == "function":
            func = tool["function"]
            declarations.append(
                types.FunctionDeclaration(
                    name=func["name"],
                    description=func.get("description", ""),
                    parameters=func.get("parameters", {"type": "object", "properties": {}}),
                )
            )
    if declarations:
        return [types.Tool(function_declarations=declarations)]
    return []


def oai_messages_to_gemini_contents(messages: List[Dict[str, Any]]):
    """Convert OpenAI-format messages to Gemini contents.

    Returns (system_instruction, contents).
    Handles: system, user, assistant, tool roles.
    Merges consecutive same-role messages as required by Gemini.
    """
    system_parts = []
    contents: List[types.Content] = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content") or ""

        if role == "system":
            system_parts.append(content)
            continue

        if role == "user":
            gemini_role = "user"
            parts = [types.Part(text=content)] if content else []

        elif role == "assistant":
            gemini_role = "model"
            parts = []
            if content:
                parts.append(types.Part(text=content))
            for tc in msg.get("tool_calls") or []:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    args = {}
                parts.append(
                    types.Part(
                        function_call=types.FunctionCall(
                            name=tc["function"]["name"],
                            args=args,
                        )
                    )
                )

        elif role == "tool":
            # Tool result → user message with FunctionResponse
            gemini_role = "user"
            tool_name = msg.get("name", "unknown")
            # Try to parse content as structured data, else wrap as string
            try:
                result_data = json.loads(content)
                if not isinstance(result_data, dict):
                    result_data = {"result": result_data}
            except (json.JSONDecodeError, TypeError):
                result_data = {"result": content}
            parts = [
                types.Part(
                    function_response=types.FunctionResponse(
                        name=tool_name,
                        response=result_data,
                    )
                )
            ]
        else:
            continue

        if not parts:
            continue

        # Merge consecutive same-role messages
        if contents and contents[-1].role == gemini_role:
            contents[-1] = types.Content(
                role=gemini_role,
                parts=list(contents[-1].parts) + parts,
            )
        else:
            contents.append(types.Content(role=gemini_role, parts=parts))

    # Gemini requires conversation to end with user role
    if not contents or contents[-1].role != "user":
        contents.append(types.Content(role="user", parts=[types.Part(text="Please continue.")]))

    system_instruction = "\n".join(system_parts).strip() or None
    return system_instruction, contents


class GeminiClient:
    """OpenAI-compatible client for Google Gemini API (AI Studio or Vertex AI)."""

    def __init__(self, **kwargs):
        project = kwargs.get("project") or os.getenv("GOOGLE_CLOUD_PROJECT")
        location = kwargs.get("location") or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        api_key = kwargs.get("api_key") or os.getenv("GOOGLE_API_KEY")

        if project:
            # Vertex AI — uses Application Default Credentials ($300 GCP credit)
            self._client = genai.Client(vertexai=True, project=project, location=location)
            self._vertex = True
        elif api_key:
            # AI Studio — uses prepay credits
            self._client = genai.Client(api_key=api_key)
            self._vertex = False
        else:
            raise AssertionError(
                "Provide 'project' (Vertex AI) or 'api_key' (AI Studio) in config, "
                "or set GOOGLE_CLOUD_PROJECT / GOOGLE_API_KEY env variable."
            )

    def message_retrieval(self, response) -> List:
        return [choice.message for choice in response.choices]

    def cost(self, response) -> float:
        return response.cost

    @staticmethod
    def get_usage(response) -> Dict:
        return {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
            "cost": response.cost,
            "model": response.model,
        }

    def create(self, params: Dict) -> ChatCompletion:
        model = params.get("model", "gemini-2.0-flash")
        messages = params.get("messages", [])
        max_tokens = params.get("max_tokens", 4096)
        temperature = params.get("temperature", 0.5)
        oai_tools = params.get("tools", None)

        system_instruction, contents = oai_messages_to_gemini_contents(messages)

        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
        )
        if system_instruction:
            config.system_instruction = system_instruction
        if oai_tools:
            config.tools = oai_tools_to_gemini_tools(oai_tools)

        max_retries = 10
        response = None
        for attempt in range(max_retries):
            try:
                response = self._client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
                break
            except ClientError as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    delay = 60
                    warnings.warn(f"Gemini rate limit (429). Retry in {delay}s...", UserWarning)
                    time.sleep(delay)
                else:
                    raise RuntimeError(f"Gemini API error: {e}")
            except Exception as e:
                raise RuntimeError(f"Gemini API exception: {e}")

        if response is None:
            raise RuntimeError(f"No response from Gemini after {max_retries} retries.")

        # Parse response parts
        text_parts = []
        tool_calls = []
        candidate = response.candidates[0]
        for part in candidate.content.parts:
            if part.text:
                text_parts.append(part.text)
            elif part.function_call:
                tool_calls.append(
                    ChatCompletionMessageToolCall(
                        id=f"call_{random.randint(0, 99999)}",
                        type="function",
                        function=Function(
                            name=part.function_call.name,
                            arguments=json.dumps(dict(part.function_call.args)),
                        ),
                    )
                )

        text_content = "".join(text_parts) or None

        message = ChatCompletionMessage(
            role="assistant",
            content=text_content,
            function_call=None,
            tool_calls=tool_calls if tool_calls else None,
        )

        prompt_tokens = response.usage_metadata.prompt_token_count or 0
        completion_tokens = response.usage_metadata.candidates_token_count or 0

        return ChatCompletion(
            id=str(random.randint(0, 1000)),
            model=model,
            created=int(time.time()),
            object="chat.completion",
            choices=[Choice(finish_reason="stop", index=0, message=message)],
            usage=CompletionUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
            cost=calculate_gemini_cost(prompt_tokens, completion_tokens, model),
        )
