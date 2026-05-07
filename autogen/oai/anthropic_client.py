"""OpenAI-compatible client for Anthropic Claude API.

Example:
    llm_config={
        "config_list": [{
            "api_type": "anthropic",
            "model": "claude-sonnet-4-6",
            "api_key": os.environ.get("ANTHROPIC_API_KEY")
        }]
    }

    agent = autogen.AssistantAgent("my_agent", llm_config=llm_config)
"""

from __future__ import annotations

import json
import os
import random
import time
import warnings
from typing import Any, Dict, List, Optional

import anthropic
from openai.types.chat import ChatCompletion
from openai.types.chat.chat_completion import ChatCompletionMessage, Choice
from openai.types.chat.chat_completion_message_tool_call import ChatCompletionMessageToolCall, Function
from openai.types.completion_usage import CompletionUsage

ANTHROPIC_PRICING = {
    "claude-opus-4-7":   {"input": 15.0,  "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0,   "output": 15.0},
    "claude-sonnet-4-5": {"input": 3.0,   "output": 15.0},
    "claude-haiku-4-5":  {"input": 0.8,   "output": 4.0},
}


def calculate_anthropic_cost(input_tokens: int, output_tokens: int, model: str) -> float:
    for key, price in ANTHROPIC_PRICING.items():
        if key in model:
            return price["input"] * input_tokens / 1e6 + price["output"] * output_tokens / 1e6
    warnings.warn(f"Cost not implemented for {model}, using Sonnet pricing.", UserWarning)
    return 3.0 * input_tokens / 1e6 + 15.0 * output_tokens / 1e6


def oai_tools_to_anthropic_tools(tools: List[Dict]) -> List[Dict]:
    """Convert OpenAI tool definitions to Anthropic format."""
    anthropic_tools = []
    for tool in tools:
        if tool.get("type") == "function":
            func = tool["function"]
            anthropic_tools.append({
                "name": func["name"],
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })
    return anthropic_tools


def oai_messages_to_anthropic_messages(messages: List[Dict[str, Any]]):
    """Convert OpenAI-format messages to Anthropic format.

    Returns (system_prompt, anthropic_messages).
    Handles: system, user, assistant, tool roles.
    """
    system_parts = []
    anthropic_messages = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content") or ""

        if role == "system":
            system_parts.append(content)

        elif role == "user":
            if anthropic_messages and anthropic_messages[-1]["role"] == "user":
                # Merge consecutive user messages
                prev = anthropic_messages[-1]["content"]
                if isinstance(prev, str):
                    anthropic_messages[-1]["content"] = prev + "\n" + content
                elif isinstance(prev, list):
                    prev.append({"type": "text", "text": content})
            else:
                anthropic_messages.append({"role": "user", "content": content})

        elif role == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                # Assistant message with tool calls
                content_blocks: List[Dict] = []
                if content:
                    content_blocks.append({"type": "text", "text": content})
                for tc in tool_calls:
                    try:
                        args = json.loads(tc["function"]["arguments"])
                    except (json.JSONDecodeError, KeyError):
                        args = {}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["function"]["name"],
                        "input": args,
                    })
                anthropic_messages.append({"role": "assistant", "content": content_blocks})
            else:
                if anthropic_messages and anthropic_messages[-1]["role"] == "assistant":
                    prev = anthropic_messages[-1]["content"]
                    if isinstance(prev, str):
                        anthropic_messages[-1]["content"] = prev + "\n" + content
                    else:
                        prev.append({"type": "text", "text": content})
                else:
                    anthropic_messages.append({"role": "assistant", "content": content})

        elif role == "tool":
            # Tool result — must be a user message with tool_result block
            tool_use_id = msg.get("tool_call_id", "unknown")
            tool_result_block = {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": content,
            }
            if anthropic_messages and anthropic_messages[-1]["role"] == "user":
                prev = anthropic_messages[-1]["content"]
                if isinstance(prev, list):
                    prev.append(tool_result_block)
                else:
                    anthropic_messages[-1]["content"] = [
                        {"type": "text", "text": prev},
                        tool_result_block,
                    ]
            else:
                anthropic_messages.append({"role": "user", "content": [tool_result_block]})

    # Anthropic requires first message from user
    if not anthropic_messages or anthropic_messages[0]["role"] != "user":
        anthropic_messages.insert(0, {"role": "user", "content": "Please continue."})

    # Anthropic requires last message from user
    if anthropic_messages[-1]["role"] != "user":
        anthropic_messages.append({"role": "user", "content": "Please continue."})

    return "\n".join(system_parts).strip(), anthropic_messages


class AnthropicClient:
    """OpenAI-compatible client for Anthropic Claude API."""

    def __init__(self, **kwargs):
        self.api_key = kwargs.get("api_key") or os.getenv("ANTHROPIC_API_KEY")
        assert self.api_key, (
            "Provide api_key in config or set ANTHROPIC_API_KEY env variable."
        )
        self._client = anthropic.Anthropic(api_key=self.api_key)

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
        model = params.get("model", "claude-sonnet-4-6")
        messages = params.get("messages", [])
        max_tokens = params.get("max_tokens", 4096)
        temperature = params.get("temperature", 0.5)
        oai_tools = params.get("tools", None)

        system_prompt, anthropic_messages = oai_messages_to_anthropic_messages(messages)

        call_kwargs: Dict[str, Any] = dict(
            model=model,
            messages=anthropic_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if system_prompt:
            call_kwargs["system"] = system_prompt
        if oai_tools:
            anthropic_tools = oai_tools_to_anthropic_tools(oai_tools)
            call_kwargs["tools"] = anthropic_tools

        max_retries = 10
        response = None
        for attempt in range(max_retries):
            try:
                response = self._client.messages.create(**call_kwargs)
                break
            except anthropic.RateLimitError:
                delay = 60
                warnings.warn(f"Anthropic rate limit. Retry in {delay}s...", UserWarning)
                time.sleep(delay)
            except anthropic.APIStatusError as e:
                if e.status_code == 529:
                    delay = 30
                    warnings.warn(f"Anthropic overloaded. Retry in {delay}s...", UserWarning)
                    time.sleep(delay)
                else:
                    raise RuntimeError(f"Anthropic API error: {e}")
            except Exception as e:
                raise RuntimeError(f"Anthropic exception: {e}")

        if response is None:
            raise RuntimeError(f"No response from Anthropic after {max_retries} retries.")

        # Parse response content blocks
        text_parts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ChatCompletionMessageToolCall(
                        id=block.id,
                        type="function",
                        function=Function(
                            name=block.name,
                            arguments=json.dumps(block.input),
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

        prompt_tokens = response.usage.input_tokens
        completion_tokens = response.usage.output_tokens

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
            cost=calculate_anthropic_cost(prompt_tokens, completion_tokens, model),
        )
