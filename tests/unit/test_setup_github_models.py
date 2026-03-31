from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_scripts_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

setup_github_models = importlib.import_module("setup_github_models")
_upsert_env = setup_github_models._upsert_env
_pick_model = setup_github_models._pick_model
_fetch_catalog = setup_github_models._fetch_catalog
main = setup_github_models.main


class TestUpsertEnv:
    def test_inserts_new_key(self):
        lines = ["FOO=bar\n"]
        result = _upsert_env(lines, "BAZ", "qux")
        assert "BAZ=qux\n" in result
        assert "FOO=bar\n" in result

    def test_replaces_existing_key(self):
        lines = ["LLM_PROVIDER=openai\n", "LLM_MODEL=gpt-4o\n"]
        result = _upsert_env(lines, "LLM_PROVIDER", "github_models")
        assert "LLM_PROVIDER=github_models\n" in result
        assert "LLM_PROVIDER=openai\n" not in result
        assert "LLM_MODEL=gpt-4o\n" in result

    def test_handles_empty_lines(self):
        lines: list[str] = []
        result = _upsert_env(lines, "KEY", "val")
        assert result == ["KEY=val\n"]

    def test_preserves_comments(self):
        lines = ["# LLM Config\n", "LLM_PROVIDER=openai\n"]
        result = _upsert_env(lines, "LLM_PROVIDER", "github_models")
        assert result[0] == "# LLM Config\n"
        assert result[1] == "LLM_PROVIDER=github_models\n"

    def test_does_not_match_partial_key(self):
        lines = ["LLM_PROVIDER_EXTRA=foo\n", "LLM_PROVIDER=openai\n"]
        result = _upsert_env(lines, "LLM_PROVIDER", "github_models")
        assert "LLM_PROVIDER_EXTRA=foo\n" in result
        assert "LLM_PROVIDER=github_models\n" in result

    def test_replaces_empty_value(self):
        lines = ["LLM_BASE_URL=\n"]
        result = _upsert_env(lines, "LLM_BASE_URL", "https://example.com")
        assert "LLM_BASE_URL=https://example.com\n" in result


# ---------------------------------------------------------------------------
# Fake model dicts matching GitHub Models catalog shape
# ---------------------------------------------------------------------------
_FAKE_MODELS: list[dict[str, str]] = [
    {"name": "gpt-4o", "publisher": "openai", "task": "chat-completion"},
    {"name": "gpt-4o-mini", "publisher": "openai", "task": "chat-completion"},
    {"name": "o3-mini", "publisher": "openai", "task": "chat-completion"},
]


class TestPickModel:
    """Tests for _pick_model() — interactive model selection helper."""

    def test_select_by_number(self):
        """User enters a number to pick from the menu."""
        with patch("builtins.input", return_value="1"):
            result = _pick_model(_FAKE_MODELS, "primary")
        assert result == "openai/gpt-4o"

    def test_select_by_number_last(self):
        """User picks the last model in the list."""
        with patch("builtins.input", return_value="3"):
            result = _pick_model(_FAKE_MODELS, "primary")
        assert result == "openai/o3-mini"

    def test_select_by_name(self):
        """User types a model name directly instead of a number."""
        with patch("builtins.input", return_value="my-custom/model"):
            result = _pick_model(_FAKE_MODELS, "primary")
        assert result == "my-custom/model"

    def test_enter_returns_default(self):
        """Pressing Enter with no input returns the default."""
        with patch("builtins.input", return_value=""):
            result = _pick_model(_FAKE_MODELS, "fast", default="openai/gpt-4o")
        assert result == "openai/gpt-4o"

    def test_enter_returns_empty_when_no_default(self):
        """Pressing Enter with no default returns empty string."""
        with patch("builtins.input", return_value=""):
            result = _pick_model(_FAKE_MODELS, "fallback")
        assert result == ""

    def test_invalid_number_retries(self):
        """Invalid number index retries, then accepts valid input."""
        with patch("builtins.input", side_effect=["99", "2"]):
            result = _pick_model(_FAKE_MODELS, "primary")
        assert result == "openai/gpt-4o-mini"

    def test_model_without_publisher(self):
        """Model dict missing publisher returns bare name."""
        models = [{"name": "llama3", "task": "chat"}]
        with patch("builtins.input", return_value="1"):
            result = _pick_model(models, "primary")
        assert result == "llama3"


class TestFetchCatalog:
    """Tests for _fetch_catalog() — HTTP catalog fetch."""

    def test_success_returns_list(self):
        """Successful catalog fetch returns list of model dicts."""
        payload = json.dumps(_FAKE_MODELS).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = payload
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _fetch_catalog("ghp_faketoken1234")
        assert len(result) == 3
        assert result[0]["name"] == "gpt-4o"

    def test_success_returns_nested_models_key(self):
        """Catalog response with 'models' key extracts correctly."""
        payload = json.dumps({"models": _FAKE_MODELS}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = payload
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _fetch_catalog("ghp_faketoken1234")
        assert len(result) == 3

    def test_network_error_returns_empty(self):
        """Network failure returns empty list, no exception raised."""
        with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
            result = _fetch_catalog("ghp_faketoken1234")
        assert result == []

    def test_auth_error_returns_empty(self):
        """HTTP 401 returns empty list."""
        import urllib.error
        from email.message import Message

        hdrs = Message()
        err = urllib.error.HTTPError(
            url="https://models.github.ai/catalog/models",
            code=401,
            msg="Unauthorized",
            hdrs=hdrs,
            fp=None,
        )
        with patch("urllib.request.urlopen", side_effect=err):
            result = _fetch_catalog("ghp_badtoken")
        assert result == []


class TestMainFlow:
    """Tests for main() — full interactive setup flow."""

    def _run_main(
        self,
        inputs: list[str],
        *,
        auto_mode: bool = False,
        confirm: str = "",
    ) -> str:
        """Run main() with mocked I/O and return written .env content.

        Args:
            inputs: Sequence of input() responses.
            auto_mode: Whether to enable auto mode.
            confirm: Final confirm response ("" = accept default Y).
        """
        # Build input sequence:
        # 1. PAT
        # 2. Primary model pick
        # 3. Auto mode y/N
        # If auto: 4. fast model, 5. quality model
        # Then: fallback model
        # Then: confirm
        all_inputs = list(inputs)

        written_content: list[str] = []

        mock_env_file = MagicMock()
        mock_env_file.exists.return_value = True
        mock_env_file.read_text.return_value = "LLM_PROVIDER=openai\n"
        mock_env_file.write_text = lambda content, **kw: written_content.append(content)

        with (
            patch.object(setup_github_models, "ENV_FILE", mock_env_file),
            patch.object(setup_github_models, "_fetch_catalog", return_value=_FAKE_MODELS),
            patch.object(setup_github_models, "_test_inference", return_value=True),
            patch("builtins.input", side_effect=all_inputs),
        ):
            main()

        assert len(written_content) == 1, "Expected exactly one write_text call"
        return written_content[0]

    def test_basic_flow_no_auto(self):
        """Basic flow: PAT, primary model, no auto, no fallback, confirm."""
        inputs = [
            "ghp_testtoken1234567890",  # PAT
            "1",  # primary = openai/gpt-4o
            "n",  # auto mode = no
            "",  # fallback = skip
            "",  # confirm = Y
        ]
        content = self._run_main(inputs)
        assert "LLM_PROVIDER=github_models" in content
        assert "LLM_MODEL=openai/gpt-4o" in content
        assert "LLM_API_KEY=ghp_testtoken1234567890" in content
        assert "LLM_AUTO_MODE=false" in content

    def test_auto_mode_with_all_models(self):
        """Auto mode: picks fast, quality, and fallback models."""
        inputs = [
            "ghp_testtoken1234567890",  # PAT
            "1",  # primary = openai/gpt-4o
            "y",  # auto mode = yes
            "2",  # fast = openai/gpt-4o-mini
            "1",  # quality = openai/gpt-4o
            "3",  # fallback = openai/o3-mini
            "",  # confirm = Y
        ]
        content = self._run_main(inputs, auto_mode=True)
        assert "LLM_AUTO_MODE=true" in content
        assert "LLM_FAST_MODEL=openai/gpt-4o-mini" in content
        assert "LLM_QUALITY_MODEL=openai/gpt-4o" in content
        assert "LLM_FALLBACK_MODEL=openai/o3-mini" in content

    def test_fallback_prompted_without_auto_mode(self):
        """Critical O3 fix: fallback model is always prompted, even without auto mode.

        This verifies the fix where the fallback_model prompt was moved
        outside the auto_mode conditional block.
        """
        inputs = [
            "ghp_testtoken1234567890",  # PAT
            "1",  # primary = openai/gpt-4o
            "n",  # auto mode = no
            "3",  # fallback = openai/o3-mini (MUST be prompted!)
            "",  # confirm = Y
        ]
        content = self._run_main(inputs)
        assert "LLM_FALLBACK_MODEL=openai/o3-mini" in content
        assert "LLM_AUTO_MODE=false" in content

    def test_env_file_written_with_all_keys(self):
        """All expected LLM_ keys appear in the written .env."""
        inputs = [
            "ghp_testtoken1234567890",
            "1",
            "n",
            "",  # fallback = skip
            "",  # confirm
        ]
        content = self._run_main(inputs)
        expected_keys = [
            "LLM_PROVIDER=",
            "LLM_MODEL=",
            "LLM_API_KEY=",
            "LLM_BASE_URL=",
            "LLM_FAST_MODEL=",
            "LLM_QUALITY_MODEL=",
            "LLM_FALLBACK_MODEL=",
            "LLM_AUTO_MODE=",
        ]
        for key in expected_keys:
            assert key in content, f"Missing key in .env: {key}"

    def test_abort_on_empty_pat(self):
        """Empty PAT input causes sys.exit(1)."""
        with (
            patch("builtins.input", return_value=""),
            pytest.raises(SystemExit, match="1"),
        ):
            main()

    def test_abort_on_catalog_failure(self):
        """Failed catalog fetch causes sys.exit(1)."""
        with (
            patch.object(setup_github_models, "_fetch_catalog", return_value=[]),
            patch("builtins.input", return_value="ghp_test"),
            pytest.raises(SystemExit, match="1"),
        ):
            main()

    def test_abort_on_no_primary(self):
        """Skipping primary model selection causes sys.exit(1)."""
        inputs = [
            "ghp_testtoken1234567890",  # PAT
            "",  # primary = skip → abort
        ]
        with (
            patch.object(setup_github_models, "_fetch_catalog", return_value=_FAKE_MODELS),
            patch("builtins.input", side_effect=inputs),
            pytest.raises(SystemExit, match="1"),
        ):
            main()

    def test_abort_on_user_decline(self):
        """User declining the confirm prompt causes sys.exit(0)."""
        inputs = [
            "ghp_testtoken1234567890",
            "1",
            "n",
            "",  # fallback = skip
            "n",  # confirm = no
        ]
        with (
            patch.object(
                setup_github_models,
                "ENV_FILE",
                MagicMock(
                    exists=MagicMock(return_value=True), read_text=MagicMock(return_value="")
                ),
            ),
            patch.object(setup_github_models, "_fetch_catalog", return_value=_FAKE_MODELS),
            patch.object(setup_github_models, "_test_inference", return_value=True),
            patch("builtins.input", side_effect=inputs),
            pytest.raises(SystemExit, match="0"),
        ):
            main()

    def test_inference_failure_continues(self):
        """Inference test failure doesn't abort — flow continues."""
        inputs = [
            "ghp_testtoken1234567890",
            "1",
            "n",
            "",  # fallback = skip
            "",  # confirm
        ]
        written_content: list[str] = []
        mock_env_file = MagicMock()
        mock_env_file.exists.return_value = True
        mock_env_file.read_text.return_value = ""
        mock_env_file.write_text = lambda content, **kw: written_content.append(content)

        with (
            patch.object(setup_github_models, "ENV_FILE", mock_env_file),
            patch.object(setup_github_models, "_fetch_catalog", return_value=_FAKE_MODELS),
            patch.object(setup_github_models, "_test_inference", return_value=False),
            patch("builtins.input", side_effect=inputs),
        ):
            main()

        assert len(written_content) == 1
        assert "LLM_MODEL=openai/gpt-4o" in written_content[0]
