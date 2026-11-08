"""The only module that knows Gemini. Provider-neutral messages in, ModelReply out.

Messages (also what the session store keeps):
- {"role": "user", "content": str}
- {"role": "assistant", "content": str | None, "tool_calls": [{"id", "name", "args", "thought_signature"?}]}
- {"role": "tool", "tool_call_id": str, "name": str, "content": dict}

Tool specs: [{"name", "description", "parameters": JSON schema}].
The API key comes from GEMINI_API_KEY (or GOOGLE_API_KEY) and is never logged; the model from GEMINI_MODEL.
"""
import base64
import logging
import os
import time
from dataclasses import dataclass, field

from google import genai
from google.genai import errors, types

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.8-flash"
MAX_OUTPUT_TOKENS = 8192  # thinking tokens count against this cap, so it must leave room for them
RETRY_DELAY_S = 5.0
REFUSAL_REASONS = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "LANGUAGE"}


class ConfigError(RuntimeError):
    """Missing or invalid configuration (for example no API key)."""


class ModelError(RuntimeError):
    """The model call failed."""


class RateLimitError(ModelError):
    """Rate limited even after the one retry."""


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict
    thought_signature: str | None = None

    def to_message(self) -> dict:
        out = {"id": self.id, "name": self.name, "args": self.args}
        if self.thought_signature:
            out["thought_signature"] = self.thought_signature
        return out


@dataclass
class ModelReply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"  # end_turn | tool_use | max_tokens | refusal | other
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    model: str = ""


_client = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise ConfigError("GEMINI_API_KEY is not set in the environment")
        _client = genai.Client(api_key=key)
    return _client


def model_name() -> str:
    return os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)


def to_contents(messages: list[dict]) -> list[types.Content]:
    contents: list[types.Content] = []
    for m in messages:
        role = m["role"]
        if role == "user":
            contents.append(types.Content(role="user", parts=[types.Part(text=m["content"])]))
        elif role == "assistant":
            parts = [types.Part(text=m["content"])] if m.get("content") else []
            for tc in m.get("tool_calls") or []:
                sig = tc.get("thought_signature")
                parts.append(types.Part(
                    function_call=types.FunctionCall(id=tc.get("id"), name=tc["name"], args=tc.get("args") or {}),
                    thought_signature=base64.b64decode(sig) if sig else None,
                ))
            contents.append(types.Content(role="model", parts=parts))
        elif role == "tool":
            part = types.Part(function_response=types.FunctionResponse(
                id=m.get("tool_call_id"), name=m["name"], response={"result": m["content"]}))
            prev = contents[-1] if contents else None
            if prev is not None and prev.role == "user" and prev.parts and prev.parts[0].function_response:
                prev.parts.append(part)
            else:
                contents.append(types.Content(role="user", parts=[part]))
        else:
            raise ValueError(f"unknown message role {role!r}")
    return contents


def to_tools(tool_specs: list[dict]) -> list[types.Tool]:
    if not tool_specs:
        return []
    decls = [types.FunctionDeclaration(name=s["name"], description=s.get("description", ""),
                                       parameters_json_schema=s.get("parameters") or {"type": "object", "properties": {}})
             for s in tool_specs]
    return [types.Tool(function_declarations=decls)]


def _stop_reason(finish: str | None, has_calls: bool) -> str:
    if has_calls:
        return "tool_use"
    if finish in (None, "STOP", "FINISH_REASON_UNSPECIFIED"):
        return "end_turn"
    if finish == "MAX_TOKENS":
        return "max_tokens"
    if finish in REFUSAL_REASONS:
        return "refusal"
    return "other"


def from_response(resp: types.GenerateContentResponse, model: str) -> ModelReply:
    usage = resp.usage_metadata
    tokens = {"input_tokens": (usage.prompt_token_count or 0) if usage else 0,
              "output_tokens": (usage.candidates_token_count or 0) if usage else 0,
              "thinking_tokens": (usage.thoughts_token_count or 0) if usage else 0}
    if not resp.candidates:
        block = resp.prompt_feedback.block_reason if resp.prompt_feedback else None
        return ModelReply(text="", stop_reason="refusal" if block else "other", model=model, **tokens)
    cand = resp.candidates[0]
    texts, calls = [], []
    for i, part in enumerate((cand.content.parts if cand.content else None) or []):
        if part.thought:
            continue
        if part.function_call:
            fc = part.function_call
            sig = base64.b64encode(part.thought_signature).decode() if part.thought_signature else None
            calls.append(ToolCall(id=fc.id or f"call_{i}", name=fc.name, args=dict(fc.args or {}), thought_signature=sig))
        elif part.text:
            texts.append(part.text)
    finish = cand.finish_reason.name if cand.finish_reason is not None else None
    return ModelReply(text="".join(texts), tool_calls=calls, stop_reason=_stop_reason(finish, bool(calls)),
                      model=resp.model_version or model, **tokens)


def _is_rate_limit(e: Exception) -> bool:
    return isinstance(e, errors.APIError) and e.code == 429


def complete(messages: list[dict], system: str, tool_specs: list[dict] | None = None,
             max_output_tokens: int = MAX_OUTPUT_TOKENS) -> ModelReply:
    """One model call. One retry on a rate-limit error; any other API failure raises ModelError."""
    client = get_client()
    model = model_name()
    tools = to_tools(tool_specs or [])
    config = types.GenerateContentConfig(
        system_instruction=system,
        tools=tools or None,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        max_output_tokens=max_output_tokens,
    )
    return from_response(_generate(client, model, to_contents(messages), config), model)


def transcribe(audio: bytes, mime_type: str, hint: str) -> str:
    """Speech to text with the same model. `hint` lists words the speaker is likely to use (airport codes and
    names), so they are not misheard. Raises the same errors as `complete`."""
    client = get_client()
    model = model_name()
    prompt = ("Transcribe this spoken question in English. Return only the words spoken, with no comment. "
              f"The speaker may use these words: {hint}")
    contents = [types.Content(role="user", parts=[types.Part.from_bytes(data=audio, mime_type=mime_type),
                                                  types.Part(text=prompt)])]
    config = types.GenerateContentConfig(max_output_tokens=MAX_OUTPUT_TOKENS)
    return from_response(_generate(client, model, contents, config), model).text.strip()


def _generate(client, model: str, contents: list[types.Content],
              config: types.GenerateContentConfig) -> types.GenerateContentResponse:
    """One retry on a rate-limit error; any other API failure raises ModelError."""
    for attempt in (1, 2):
        try:
            return client.models.generate_content(model=model, contents=contents, config=config)
        except errors.APIError as e:
            if _is_rate_limit(e):
                if attempt == 1:
                    log.warning("rate limited by the model API; retrying once in %.0fs", RETRY_DELAY_S)
                    time.sleep(RETRY_DELAY_S)
                    continue
                raise RateLimitError("The model is rate limited right now; please try again in a minute.") from e
            raise ModelError(f"model call failed with HTTP {e.code}") from e
        except Exception as e:  # network errors and SDK bugs surface as one typed error
            raise ModelError(f"model call failed: {type(e).__name__}") from e
    raise AssertionError("unreachable")
