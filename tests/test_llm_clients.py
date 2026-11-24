"""Unit tests for AnthropicClient, OpenAIClient, make_client, and extract_sql."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock
import pytest

from promptquery.llm import (
    AnthropicClient,
    OpenAIClient,
    extract_sql,
    make_client,
)


@pytest.fixture(autouse=True)
def mock_openai_if_missing(monkeypatch):
    """Ensure tests run smoothly even if optional promptquery[openai] extra is not installed."""
    try:
        import openai  # noqa: F401
    except ImportError:
        mock_openai = MagicMock()
        monkeypatch.setitem(sys.modules, "openai", mock_openai)


class DummyBlock:
    def __init__(self, text: str | None = None, thinking: str | None = None):
        if text is not None:
            self.text = text
        if thinking is not None:
            self.thinking = thinking


class DummyResponse:
    def __init__(self, content: list[DummyBlock]):
        self.content = content


def test_anthropic_client_generate_omits_temperature(monkeypatch):
    """Verify that AnthropicClient.generate does NOT pass 'temperature' to messages.create."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    client = AnthropicClient(model="claude-3-7-sonnet-latest")

    mock_messages = MagicMock()
    mock_messages.create.return_value = DummyResponse(
        content=[DummyBlock(text="SELECT count(*) FROM sales_orders;")]
    )
    client._client.messages = mock_messages

    sql = client.generate("system prompt", "user question")

    assert sql == "SELECT count(*) FROM sales_orders;"
    mock_messages.create.assert_called_once()
    _, kwargs = mock_messages.create.call_args

    assert "temperature" not in kwargs, "Anthropic messages.create() must not receive 'temperature'"
    assert kwargs["model"] == "claude-3-7-sonnet-latest"
    assert kwargs["max_tokens"] == 2000
    assert kwargs["system"] == "system prompt"
    assert kwargs["messages"] == [{"role": "user", "content": "user question"}]


def test_anthropic_client_handles_thinking_blocks(monkeypatch):
    """Verify that AnthropicClient cleanly ignores thinking blocks and extracts only text blocks."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    client = AnthropicClient(model="claude-3-7-sonnet-latest")

    mock_messages = MagicMock()
    mock_messages.create.return_value = DummyResponse(
        content=[
            DummyBlock(thinking="Let's formulate the SQL query..."),
            DummyBlock(text="SELECT * FROM fin_accounts;"),
        ]
    )
    client._client.messages = mock_messages

    result = client.generate("system", "user")
    assert result == "SELECT * FROM fin_accounts;"


def test_anthropic_client_handles_unexpected_temperature_kwarg_defensively(monkeypatch):
    """Verify that if messages.create rejects temperature with TypeError, it recovers cleanly."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    client = AnthropicClient(model="claude-3-7-sonnet-latest")

    mock_messages = MagicMock()
    # First call simulates a legacy wrapper rejecting temperature, second call succeeds
    def mock_create(**kwargs):
        if "temperature" in kwargs:
            raise TypeError("Messages.create() got an unexpected keyword argument 'temperature'")
        return DummyResponse(content=[DummyBlock(text="SELECT 1;")])

    mock_messages.create.side_effect = mock_create
    client._client.messages = mock_messages

    result = client.generate("system", "user")
    assert result == "SELECT 1;"


def test_openai_client_chat_model_generate(monkeypatch):
    """Verify standard OpenAI models pass temperature=0 and max_tokens=2000."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    client = OpenAIClient(model="gpt-4o")

    mock_completions = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "SELECT * FROM sales_customers;"
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    mock_completions.create.return_value = mock_resp
    client._client.chat.completions = mock_completions

    sql = client.generate("system prompt", "user query")
    assert sql == "SELECT * FROM sales_customers;"

    mock_completions.create.assert_called_once()
    _, kwargs = mock_completions.create.call_args
    assert kwargs["temperature"] == 0
    assert kwargs["max_tokens"] == 2000
    assert "max_completion_tokens" not in kwargs


def test_openai_client_reasoning_model_omits_temperature(monkeypatch):
    """Verify reasoning models (o1, o3, etc.) use max_completion_tokens and omit temperature."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    client = OpenAIClient(model="o3-mini")

    mock_completions = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "SELECT * FROM hr_employees;"
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    mock_completions.create.return_value = mock_resp
    client._client.chat.completions = mock_completions

    sql = client.generate("system prompt", "user query")
    assert sql == "SELECT * FROM hr_employees;"

    mock_completions.create.assert_called_once()
    _, kwargs = mock_completions.create.call_args
    assert "temperature" not in kwargs, "Reasoning models must not receive 'temperature'"
    assert "seed" not in kwargs
    assert kwargs["max_completion_tokens"] == 4000


def test_make_client_inferences(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    c1 = make_client("claude-3-7-sonnet")
    assert isinstance(c1, AnthropicClient)
    assert c1.model == "claude-3-7-sonnet"

    c2 = make_client("openai/gpt-4o")
    assert isinstance(c2, OpenAIClient)
    assert c2.model == "gpt-4o"

    c3 = make_client("anthropic/claude-3-5-haiku")
    assert isinstance(c3, AnthropicClient)
    assert c3.model == "claude-3-5-haiku"


def test_extract_sql_variations():
    assert extract_sql("SELECT 1;") == "SELECT 1"
    assert extract_sql("```sql\nSELECT * FROM t;\n```") == "SELECT * FROM t"
    assert extract_sql("Here is query:\n```\nSELECT id FROM items;\n```") == "SELECT id FROM items"
    assert extract_sql("  SELECT col FROM tbl ;  ") == "SELECT col FROM tbl"
