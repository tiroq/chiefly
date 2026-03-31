from __future__ import annotations

import hashlib
import hmac
import time
from types import SimpleNamespace
from typing import Callable, cast
from urllib.parse import urlencode
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from apps.api.miniapp import auth as miniapp_auth

validate_init_data = cast(
    Callable[[str, str], dict[str, str]],
    getattr(miniapp_auth, "_validate_init_data"),
)


def _build_init_data(bot_token: str, auth_date: int | None = None, **extra: str) -> str:
    payload: dict[str, str] = {
        "user": '{"id":12345}',
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
    }
    payload.update(extra)

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(payload.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    payload["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(payload)


class TestValidateInitData:
    def test_valid_signature_passes(self):
        bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        init_data = _build_init_data(bot_token)

        parsed = validate_init_data(init_data, bot_token)

        assert parsed["user"] == '{"id":12345}'
        assert "hash" not in parsed

    def test_expired_auth_date_raises_401(self):
        bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        init_data = _build_init_data(bot_token, auth_date=int(time.time()) - 7200)

        with pytest.raises(HTTPException) as exc:
            _ = validate_init_data(init_data, bot_token)

        assert exc.value.status_code == 401
        assert exc.value.detail == "Init data expired"

    def test_missing_hash_raises_401(self):
        init_data = urlencode({"user": '{"id":12345}', "auth_date": str(int(time.time()))})

        with pytest.raises(HTTPException) as exc:
            _ = validate_init_data(init_data, "bot-token")

        assert exc.value.status_code == 401
        assert exc.value.detail == "Missing hash in init data"

    def test_tampered_data_raises_401(self):
        bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        payload: dict[str, str] = {
            "user": '{"id":99999}',
            "auth_date": str(int(time.time())),
            "hash": "deadbeef",
        }
        init_data = urlencode(payload)

        with pytest.raises(HTTPException) as exc:
            _ = validate_init_data(init_data, bot_token)

        assert exc.value.status_code == 401
        assert exc.value.detail == "Invalid signature"

    def test_missing_auth_date_raises_401(self):
        bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        payload = {"user": '{"id":12345}'}
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(payload.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        payload["hash"] = hmac.new(
            secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()
        init_data = urlencode(payload)

        with pytest.raises(HTTPException) as exc:
            _ = validate_init_data(init_data, bot_token)

        assert exc.value.status_code == 401
        assert exc.value.detail == "Missing auth_date"

    @patch("apps.api.miniapp.auth.get_settings")
    def test_get_settings_can_supply_bot_token_for_validation(self, mock_get_settings: MagicMock):
        bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        mock_get_settings.return_value = SimpleNamespace(telegram_bot_token=bot_token)
        init_data = _build_init_data(bot_token)

        parsed = validate_init_data(init_data, bot_token)

        assert parsed["auth_date"].isdigit()
