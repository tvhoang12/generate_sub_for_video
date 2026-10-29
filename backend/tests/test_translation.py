"""Unit tests for translation providers, Gemini integration, and Chinese homophone checking."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from app.languages import Language
from app.translation.homophones import (
    COMMON_CHINESE_HOMOPHONE_MAP,
    get_homophone_cleaning_prompt,
    get_homophone_translation_prompt,
)
from app.translation.providers import (
    GeminiProvider,
    MockProvider,
    OpenAIProvider,
    ProviderError,
    TokenOverflowError,
    make_provider,
)
from app.translation.schemas import (
    BatchItem,
    BatchTranslateResult,
    CleanResult,
    CleanedLine,
    HomophoneCorrection,
    TermSuggestion,
    TranslateResult,
    TranslatedLine,
)
from app.translation.translator import FilmContext, Translator


class DummySchema(BaseModel):
    id: int
    text: str


def test_make_provider_defaults_and_options():
    # Mock provider
    p_mock = make_provider("mock")
    assert isinstance(p_mock, MockProvider)
    assert p_mock.name == "mock"

    # OpenAI provider with key
    with patch("app.translation.providers.settings", MagicMock(openai_api_key="mock-key")), patch("openai.OpenAI"):
        p_openai = make_provider("openai", model="gpt-4o-mini")
        assert isinstance(p_openai, OpenAIProvider)
        assert p_openai.name == "openai"
        assert p_openai._model == "gpt-4o-mini"

    # Invalid provider
    with pytest.raises(ValueError, match="TRANSLATOR_PROVIDER không hợp lệ"):
        make_provider("invalid_provider")


def test_gemini_provider_missing_api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    with patch("app.translation.providers.settings", MagicMock(gemini_api_key="")):
        with pytest.raises(ProviderError, match="Chưa cấu hình GEMINI_API_KEY"):
            GeminiProvider()


def test_gemini_provider_complete_success(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-api-key")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.candidates = [MagicMock(finish_reason="STOP")]
    mock_response.parsed = DummySchema(id=1, text="测试文本")
    mock_client.models.generate_content.return_value = mock_response

    with patch("google.genai.Client", return_value=mock_client):
        provider = GeminiProvider()
        result = provider.complete("system instruction", "user prompt", DummySchema)
        assert result.id == 1
        assert result.text == "测试文本"


def test_gemini_provider_json_text_fallback(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-api-key")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.candidates = [MagicMock(finish_reason="STOP")]
    mock_response.parsed = None
    mock_response.text = '```json\n{"id": 2, "text": "已修复同音字"}\n```'
    mock_client.models.generate_content.return_value = mock_response

    with patch("google.genai.Client", return_value=mock_client):
        provider = GeminiProvider()
        result = provider.complete("system instruction", "user prompt", DummySchema)
        assert result.id == 2
        assert result.text == "已修复同音字"


def test_gemini_provider_safety_refusal(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-api-key")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_candidate = MagicMock()
    mock_candidate.finish_reason = "SAFETY"
    mock_response.candidates = [mock_candidate]
    mock_client.models.generate_content.return_value = mock_response

    with patch("google.genai.Client", return_value=mock_client):
        provider = GeminiProvider()
        with pytest.raises(ProviderError, match="an toàn"):
            provider.complete("system", "user", DummySchema)


def test_openai_provider_missing_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    with patch("app.translation.providers.settings", MagicMock(openai_api_key="")):
        with pytest.raises(ProviderError, match="Chưa cấu hình OPENAI_API_KEY"):
            OpenAIProvider()


def test_openai_provider_complete_success(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.finish_reason = "stop"
    mock_choice.message.refusal = None
    mock_choice.message.parsed = DummySchema(id=1, text="Xin chào thế giới")
    mock_response = MagicMock(choices=[mock_choice])
    mock_client.chat.completions.parse.return_value = mock_response

    with patch("openai.OpenAI", return_value=mock_client):
        provider = OpenAIProvider()
        result = provider.complete("system", "user", DummySchema)
        assert result.id == 1
        assert result.text == "Xin chào thế giới"


def test_openai_provider_json_fallback(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.finish_reason = "stop"
    mock_choice.message.refusal = None
    mock_choice.message.parsed = None
    mock_choice.message.content = '```json\n{"id": 2, "text": "Phụ đề dịch"}\n```'
    mock_response = MagicMock(choices=[mock_choice])
    mock_client.chat.completions.parse.return_value = mock_response

    with patch("openai.OpenAI", return_value=mock_client):
        provider = OpenAIProvider()
        result = provider.complete("system", "user", DummySchema)
        assert result.id == 2
        assert result.text == "Phụ đề dịch"


def test_openai_provider_refusal(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.refusal = "Nội dung vi phạm chính sách"
    mock_response = MagicMock(choices=[mock_choice])
    mock_client.chat.completions.parse.return_value = mock_response

    with patch("openai.OpenAI", return_value=mock_client):
        provider = OpenAIProvider()
        with pytest.raises(ProviderError, match="an toàn"):
            provider.complete("system", "user", DummySchema)


def test_openai_provider_token_overflow(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.finish_reason = "length"
    mock_choice.message.refusal = None
    mock_response = MagicMock(choices=[mock_choice])
    mock_client.chat.completions.parse.return_value = mock_response

    with patch("openai.OpenAI", return_value=mock_client):
        provider = OpenAIProvider()
        with pytest.raises(TokenOverflowError, match="max_tokens"):
            provider.complete("system", "user", DummySchema)


def test_openai_provider_extract_global_context(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Bối cảnh: Phim cổ trang Trung Quốc"
    mock_response = MagicMock(choices=[mock_choice])
    mock_client.chat.completions.create.return_value = mock_response

    with patch("openai.OpenAI", return_value=mock_client):
        provider = OpenAIProvider()
        ctx = provider.extract_global_context("system", "user")
        assert "Phim cổ trang" in ctx


def test_openai_provider_complete_batch(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.finish_reason = "stop"
    mock_choice.message.refusal = None
    mock_choice.message.parsed = BatchTranslateResult(
        items=[BatchItem(id=1, fixed_src="你好", trans="Chào bạn")]
    )
    mock_response = MagicMock(choices=[mock_choice])
    mock_client.chat.completions.parse.return_value = mock_response

    with patch("openai.OpenAI", return_value=mock_client):
        provider = OpenAIProvider()
        items = provider.complete_batch("system", "user")
        assert len(items) == 1
        assert items[0].id == 1
        assert items[0].trans == "Chào bạn"



def test_chinese_homophone_prompts():
    zh_prompt = get_homophone_cleaning_prompt("zh")
    assert "CHINESE HOMOPHONE ERROR CHECKING" in zh_prompt
    assert "同音字" in zh_prompt
    assert "顾总" in zh_prompt
    assert "homophone_corrections" in zh_prompt

    # For non-Chinese, prompt should be empty
    en_prompt = get_homophone_cleaning_prompt("en")
    assert en_prompt == ""

    # Translation prompt for Chinese
    zh_trans_prompt = get_homophone_translation_prompt("zh")
    assert "Chinese Homophone Context Awareness" in zh_trans_prompt


def test_chinese_homophone_common_map():
    assert "他" in COMMON_CHINESE_HOMOPHONE_MAP
    assert "在" in COMMON_CHINESE_HOMOPHONE_MAP
    assert "顾总" in COMMON_CHINESE_HOMOPHONE_MAP
    assert "权力" in COMMON_CHINESE_HOMOPHONE_MAP
    assert COMMON_CHINESE_HOMOPHONE_MAP["顾总"]["confusions"] == ["雇总"]


def test_mock_provider_clean_and_translate_with_homophones():
    provider = MockProvider()
    film = FilmContext(name="Thần Vương Trở Lại", characters="Diệp Thiên (nam chính), Cố Tuyết (nữ chính)")
    translator = Translator(provider, film)

    input_lines = [
        {"id": 1, "text": "雇总，材料准备好了。"},
        {"id": 2, "text": "在见。"},
    ]
    clean_res = translator.clean(input_lines, source_language="zh")
    assert len(clean_res.lines) == 2
    assert clean_res.lines[0].id == 1
    assert clean_res.homophone_corrections == []

    vi_lang = Language("vi", "Tiếng Việt", "Vietnamese", "Arial", "Noto Sans", None, 36)
    trans_res = translator.translate([{"id": 1, "text": clean_res.lines[0].text}], vi_lang, source_language="zh")
    assert len(trans_res.lines) == 1
    assert trans_res.lines[0].id == 1


def test_clean_result_schema_with_homophone_corrections():
    data = {
        "lines": [{"id": 1, "text": "顾总，这是合同。", "unclear": False}],
        "new_terms": [{"term": "顾总", "note": "Tổng tài Cố Dạ Bạch"}],
        "homophone_corrections": [
            {
                "id": 1,
                "original": "雇总",
                "corrected": "顾总",
                "pinyin": "gù zǒng",
                "explanation": "Tên nhân vật Tổng tài họ Cố bị ASR nhận diện nhầm thành 雇 (thuê)",
            }
        ],
    }
    result = CleanResult.model_validate(data)
    assert len(result.lines) == 1
    assert len(result.homophone_corrections) == 1
    corr = result.homophone_corrections[0]
    assert corr.id == 1
    assert corr.original == "雇总"
    assert corr.corrected == "顾总"
    assert corr.pinyin == "gù zǒng"
