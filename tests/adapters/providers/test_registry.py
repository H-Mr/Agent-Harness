"""Tests for ProviderSpec registry and lookup helpers."""

from llm_harness.adapters.providers.registry import (
    PROVIDERS,
    ProviderSpec,
    detect_provider,
    find_by_name,
)


class TestProviderSpecRegistry:
    """Provider registry: all specs defined, field presence, and lookup."""

    # ------------------------------------------------------------------
    # Registry completeness
    # ------------------------------------------------------------------

    def test_all_providers_have_required_fields(self) -> None:
        """Every ProviderSpec in the registry must have name set."""
        for spec in PROVIDERS:
            assert isinstance(spec.name, str) and spec.name, f"Missing name in {spec}"
            # backend must be one of the known types
            assert spec.backend in (
                "openai_compat", "anthropic", "azure_openai", "openai_codex",
            ), f"Unknown backend {spec.backend} for {spec.name}"

    def test_all_providers_have_display_name(self) -> None:
        """Every provider should have a display_name (even if empty string for some)."""
        for spec in PROVIDERS:
            assert hasattr(spec, "display_name")
            assert isinstance(spec.display_name, str)

    def test_all_providers_have_keywords_tuple(self) -> None:
        """Every provider must have a keywords tuple (may be empty)."""
        for spec in PROVIDERS:
            assert isinstance(spec.keywords, tuple)

    def test_provider_spec_fields_are_all_present(self) -> None:
        """ProviderSpec must contain all documented fields."""
        fields = {
            "name", "keywords", "env_key", "display_name", "backend",
            "env_extras", "is_gateway", "is_local", "detect_by_key_prefix",
            "detect_by_base_keyword", "default_api_base", "strip_model_prefix",
            "model_overrides", "is_oauth", "is_direct", "supports_prompt_caching",
        }
        spec_fields = set(ProviderSpec.__dataclass_fields__.keys())
        assert fields.issubset(spec_fields), f"Missing fields: {fields - spec_fields}"

    # ------------------------------------------------------------------
    # Lookup by name
    # ------------------------------------------------------------------

    def test_find_by_name_returns_correct_provider(self) -> None:
        """find_by_name must return the correct ProviderSpec for known names."""
        spec = find_by_name("dashscope")
        assert spec is not None
        assert spec.name == "dashscope"
        assert "qwen" in spec.keywords

        spec = find_by_name("anthropic")
        assert spec is not None
        assert spec.name == "anthropic"
        assert spec.backend == "anthropic"

    def test_find_by_name_returns_none_for_unknown(self) -> None:
        """find_by_name must return None when the name is not in the registry."""
        spec = find_by_name("nonexistent_provider_xyz")
        assert spec is None

    def test_find_by_name_normalizes_dashes(self) -> None:
        """find_by_name must convert dashes to underscores for matching."""
        spec = find_by_name("github-copilot")
        assert spec is not None
        assert spec.name == "github_copilot"

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def test_detect_by_model_name(self) -> None:
        """detect_provider must match by model-name keywords."""
        spec = detect_provider(model="gpt-4o")
        assert spec is not None
        assert spec.name == "openai"

        spec = detect_provider(model="claude-3-opus")
        assert spec is not None
        assert spec.name == "anthropic"

        spec = detect_provider(model="qwen-max")
        assert spec is not None
        assert spec.name == "dashscope"

    def test_detect_by_api_key_prefix(self) -> None:
        """detect_provider must match by API key prefix."""
        spec = detect_provider(model="", api_key="sk-or-v1-xxxx")
        assert spec is not None
        assert spec.name == "openrouter"

    def test_detect_by_base_url_keyword(self) -> None:
        """detect_provider must match by substring in api_base."""
        spec = detect_provider(model="", api_base="https://openrouter.ai/api/v1")
        assert spec is not None
        assert spec.name == "openrouter"

        spec = detect_provider(model="", api_base="https://api.siliconflow.cn/v1")
        assert spec is not None
        assert spec.name == "siliconflow"

    def test_detect_returns_none_when_no_match(self) -> None:
        """detect_provider must return None when no provider matches."""
        spec = detect_provider(model="", api_key="", api_base="")
        assert spec is None

    def test_detect_oauth_providers_skipped_in_model_match(self) -> None:
        """OAuth-based providers must be skipped during model-name matching."""
        # "copilot" would match github_copilot, but it's OAuth so skipped
        # The last non-OAuth provider with "copilot" keyword would need to match
        spec = detect_provider(model="copilot-xyz")
        # Should not match github_copilot (oauth) or openai (no copilot kw)
        assert spec is None or spec.name != "github_copilot"
