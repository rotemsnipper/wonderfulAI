import base64
import logging

import pytest
from google.genai import errors, types

from backend.agent import llm

SPECS = [{"name": "airport_profile", "description": "One airport in depth",
          "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}}]


def response(parts, finish=types.FinishReason.STOP, prompt_tokens=120, out_tokens=30, block=None):
    cands = [] if parts is None else [types.Candidate(content=types.Content(role="model", parts=parts), finish_reason=finish)]
    return types.GenerateContentResponse(
        candidates=cands, model_version="gemini-test-001",
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=prompt_tokens, candidates_token_count=out_tokens),
        prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason=block) if block else None,
    )


class FakeModels:
    def __init__(self, items):
        self.items = list(items)
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, items):
        self.models = FakeModels(items)


@pytest.fixture
def fake(monkeypatch):
    def install(*items):
        client = FakeClient(items)
        monkeypatch.setattr(llm, "_client", client)
        monkeypatch.setattr(llm.time, "sleep", lambda s: None)
        return client
    return install


def rate_limit():
    return errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}})


def test_tool_use_reply_keeps_thought_signature(fake):
    fc = types.FunctionCall(id="c1", name="airport_profile", args={"code": "SFO"})
    fake(response([types.Part(function_call=fc, thought_signature=b"sig")]))
    r = llm.complete([{"role": "user", "content": "SFO?"}], "system", SPECS)
    assert r.stop_reason == "tool_use"
    assert r.tool_calls[0].to_message() == {"id": "c1", "name": "airport_profile", "args": {"code": "SFO"},
                                            "thought_signature": base64.b64encode(b"sig").decode()}


def test_rate_limit_then_success(fake):
    client = fake(rate_limit(), response([types.Part(text="ok")]))
    assert llm.complete([{"role": "user", "content": "x"}], "s").text == "ok"
    assert len(client.models.calls) == 2


def test_rate_limit_twice_raises_typed_error(fake):
    fake(rate_limit(), rate_limit())
    with pytest.raises(llm.RateLimitError):
        llm.complete([{"role": "user", "content": "x"}], "s")


def test_other_api_error_is_model_error_without_retry(fake):
    client = fake(errors.ServerError(500, {"error": {"code": 500, "message": "boom"}}))
    with pytest.raises(llm.ModelError) as e:
        llm.complete([{"role": "user", "content": "x"}], "s")
    assert not isinstance(e.value, llm.RateLimitError) and len(client.models.calls) == 1


def test_safety_finish_and_blocked_prompt_are_refusals(fake):
    fake(response([], finish=types.FinishReason.SAFETY))
    assert llm.complete([{"role": "user", "content": "x"}], "s").stop_reason == "refusal"
    fake(response(None, block=types.BlockedReason.SAFETY))
    r = llm.complete([{"role": "user", "content": "x"}], "s")
    assert r.stop_reason == "refusal" and r.text == ""


def test_max_token_stop_reports_thinking_tokens_and_leaves_room_for_them(fake):
    resp = response([types.Part(text="LAX handled 36")], finish=types.FinishReason.MAX_TOKENS)
    resp.usage_metadata.thoughts_token_count = 1900
    client = fake(resp)
    r = llm.complete([{"role": "user", "content": "x"}], "s")
    assert r.stop_reason == "max_tokens" and r.text == "LAX handled 36" and r.thinking_tokens == 1900
    assert client.models.calls[0]["config"].max_output_tokens >= 8192


def test_messages_and_specs_are_translated(fake):
    client = fake(response([types.Part(text="done")]))
    sig = base64.b64encode(b"sig").decode()
    messages = [
        {"role": "user", "content": "Compare LAX and SNA"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "name": "airport_profile", "args": {"code": "LAX"}, "thought_signature": sig},
            {"id": "c2", "name": "airport_profile", "args": {"code": "SNA"}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "airport_profile", "content": {"delay_rate_pct": 19.66}},
        {"role": "tool", "tool_call_id": "c2", "name": "airport_profile", "content": {"delay_rate_pct": 18.34}},
    ]
    llm.complete(messages, "be brief", SPECS)
    call = client.models.calls[0]
    contents = call["contents"]
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert contents[1].parts[0].thought_signature == b"sig"
    assert [p.function_response.id for p in contents[2].parts] == ["c1", "c2"]
    assert contents[2].parts[0].function_response.response == {"result": {"delay_rate_pct": 19.66}}
    decl = call["config"].tools[0].function_declarations[0]
    assert decl.name == "airport_profile" and decl.parameters_json_schema["required"] == ["code"]
    assert call["config"].system_instruction == "be brief"
    assert call["config"].automatic_function_calling.disable is True


def test_missing_key_is_config_error(monkeypatch):
    monkeypatch.setattr(llm, "_client", None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(llm.ConfigError):
        llm.complete([{"role": "user", "content": "x"}], "s")


def test_key_never_appears_in_logs_or_errors(fake, monkeypatch, caplog):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key-123")
    fake(rate_limit(), rate_limit())
    with caplog.at_level(logging.DEBUG), pytest.raises(llm.RateLimitError) as e:
        llm.complete([{"role": "user", "content": "x"}], "s")
    assert "secret-key-123" not in caplog.text and "secret-key-123" not in str(e.value)
