import os
import unittest
from unittest.mock import patch

from app.services.provider_router import (
    DEFAULT_MODELS,
    get_configured_model,
    get_endpoint_url,
)


class ProviderRouterMistralTests(unittest.TestCase):
    def test_blank_mistral_override_uses_builtin_chat_endpoint(self):
        with patch.dict(os.environ, {"MISTRAL_API_URL": ""}, clear=False):
            self.assertEqual(
                get_endpoint_url("mistral"),
                "https://api.mistral.ai/v1/chat/completions",
            )

    def test_mistral_hostname_only_is_normalized(self):
        with patch.dict(os.environ, {"MISTRAL_API_URL": "https://api.mistral.ai"}, clear=False):
            self.assertEqual(
                get_endpoint_url("mistral"),
                "https://api.mistral.ai/v1/chat/completions",
            )

    def test_mistral_v1_base_is_normalized(self):
        with patch.dict(os.environ, {"MISTRAL_API_URL": "https://api.mistral.ai/v1"}, clear=False):
            self.assertEqual(
                get_endpoint_url("mistral"),
                "https://api.mistral.ai/v1/chat/completions",
            )

    def test_complete_mistral_endpoint_is_unchanged(self):
        endpoint = "https://api.mistral.ai/v1/chat/completions"
        with patch.dict(os.environ, {"MISTRAL_API_URL": endpoint}, clear=False):
            self.assertEqual(get_endpoint_url("mistral"), endpoint)

    def test_custom_mistral_endpoint_is_preserved_verbatim(self):
        endpoint = "https://mistral.internal.example/openai/v1/chat/completions"
        with patch.dict(os.environ, {"MISTRAL_API_URL": endpoint}, clear=False):
            self.assertEqual(get_endpoint_url("mistral"), endpoint)

    def test_mistral_model_defaults_and_explicit_override(self):
        with patch.dict(os.environ, {"MISTRAL_MODEL": ""}, clear=False):
            self.assertEqual(get_configured_model("mistral"), DEFAULT_MODELS["mistral"])
            self.assertEqual(get_configured_model("mistral"), "mistral-small-latest")
        with patch.dict(os.environ, {"MISTRAL_MODEL": "mistral-medium-latest"}, clear=False):
            self.assertEqual(get_configured_model("mistral"), "mistral-medium-latest")


if __name__ == "__main__":
    unittest.main()
