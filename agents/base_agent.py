"""
Base class for all FinAgent section agents.

Provides a shared Anthropic client and a tool-use loop helper that
handles the stop_reason == "tool_use" → execute → append → retry cycle.
"""

import json
import logging
import time
from typing import Any, Callable

import anthropic

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_TOOL_ITERATIONS = 8


class BaseAgent:
    def __init__(self, anthropic_api_key: str):
        self._client = anthropic.Anthropic(api_key=anthropic_api_key)

    def _run_tool_loop(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        tool_executors: dict[str, Callable[[dict], Any]],
        max_tokens: int = 2048,
    ) -> str:
        """
        Runs a Claude message loop with tool use until stop_reason == "end_turn".
        Returns the final text content.
        """
        current_messages = list(messages)

        for iteration in range(MAX_TOOL_ITERATIONS):
            kwargs: dict[str, Any] = dict(
                model=MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=current_messages,
            )
            if tools:
                kwargs["tools"] = tools

            try:
                response = self._client.messages.create(**kwargs)
            except anthropic.RateLimitError:
                logger.warning("Rate limited — waiting 30s before retry")
                time.sleep(30)
                response = self._client.messages.create(**kwargs)

            if response.stop_reason == "end_turn":
                return _extract_text(response)

            if response.stop_reason == "tool_use":
                # Append assistant message
                current_messages.append({
                    "role": "assistant",
                    "content": response.content,
                })
                # Execute each tool call and collect results
                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    executor = tool_executors.get(block.name)
                    if executor is None:
                        result = {"error": f"Unknown tool: {block.name}"}
                    else:
                        try:
                            result = executor(block.input)
                        except Exception as exc:
                            logger.warning("Tool %s failed: %s", block.name, exc)
                            result = {"error": str(exc)}
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })
                current_messages.append({
                    "role": "user",
                    "content": tool_results,
                })
                continue

            # Unexpected stop reason
            logger.warning("Unexpected stop_reason: %s", response.stop_reason)
            return _extract_text(response)

        logger.warning("Tool loop hit max iterations (%d)", MAX_TOOL_ITERATIONS)
        return _extract_text(response)  # type: ignore[possibly-undefined]

    def _simple_completion(
        self,
        system: str,
        user_message: str,
        max_tokens: int = 1024,
    ) -> str:
        """Simple single-turn completion without tool use."""
        try:
            response = self._client.messages.create(
                model=MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_message}],
            )
            return _extract_text(response)
        except Exception as exc:
            logger.error("Claude completion failed: %s", exc)
            return f"[Analysis unavailable: {exc}]"


def _extract_text(response: anthropic.types.Message) -> str:
    parts = [block.text for block in response.content if hasattr(block, "text")]
    return "\n".join(parts).strip()
