from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CODE_IMPLEMENT_SRC = PROJECT_ROOT / "code_implement" / "src"
if str(CODE_IMPLEMENT_SRC) not in sys.path:
    sys.path.insert(0, str(CODE_IMPLEMENT_SRC))

from mas.pipelines.common import qwen_text_provider  # noqa: E402
from mas.pipelines.kg_extraction.models import KgExtractionRunConfig  # noqa: E402


class _FakeResponse:
    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(
            {
                "choices": [{"message": {"content": "{\"ok\": true}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        ).encode("utf-8")


def test_qwen_text_request_does_not_send_local_max_input_tokens(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout: int):  # noqa: ANN001
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse()

    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setattr(qwen_text_provider.urllib.request, "urlopen", fake_urlopen)

    result = qwen_text_provider.call_qwen_text(
        "system",
        "user",
        config={
            "model": "qwen-plus",
            "max_tokens": 4096,
            "max_input_tokens": 64000,
            "timeout_seconds": 7,
        },
    )

    assert result == "{\"ok\": true}"
    assert captured["timeout"] == 7
    assert captured["payload"]["model"] == "qwen-plus"
    assert captured["payload"]["max_tokens"] == 4096
    assert "max_input_tokens" not in captured["payload"]


def test_qwen_provider_error_summary_keeps_message_and_param_without_secret() -> None:
    body = json.dumps(
        {
            "error": {
                "code": "invalid_parameter_error",
                "message": "Unsupported parameter: max_input_tokens",
                "param": "max_input_tokens",
            }
        }
    )

    summary = qwen_text_provider._summarize_provider_error(body, "secret-key")

    assert "invalid_parameter_error" in summary
    assert "Unsupported parameter" in summary
    assert "param=max_input_tokens" in summary
    assert "secret-key" not in summary


def test_kg_extraction_default_qwen_max_tokens_is_dashscope_friendly() -> None:
    assert KgExtractionRunConfig(
        enhanced_md_paths=[],
        sections_index_path=Path("sections.json"),
        standards_dir=Path("standards"),
        schema_path=Path("schema.json"),
        run_id="test",
        mock=False,
        node_model="qwen-plus",
        edge_model="qwen-plus",
        standard_model="qwen-plus",
        validation_provider="deepseek_openai_compatible",
        validation_model="deepseek-chat",
        validation_base_url="https://api.deepseek.com",
        validation_api_key_env="DEEPSEEK_API_KEY",
        max_revision_rounds=5,
    ).qwen_max_tokens == 8192
