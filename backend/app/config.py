from __future__ import annotations

import json
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "GateApp Backend"
    debug: bool = True
    api_prefix: str = "/api"
    cors_allow_origins_json: str = (
        '["http://xn--80aaachc8cmu1au8c1f.xn--p1ai", "https://xn--80aaachc8cmu1au8c1f.xn--p1ai", '
        '"http://www.xn--80aaachc8cmu1au8c1f.xn--p1ai", "https://www.xn--80aaachc8cmu1au8c1f.xn--p1ai", '
        '"http://localhost", "http://127.0.0.1", "http://localhost:80", "http://127.0.0.1:80", '
        '"http://localhost:8081", "http://127.0.0.1:8081", "http://localhost:8082", "http://127.0.0.1:8082", '
        '"http://localhost:8083", "http://127.0.0.1:8083", "http://localhost:19006", "http://127.0.0.1:19006"]'
    )
    allowed_hosts_json: str = (
        '["xn--80aaachc8cmu1au8c1f.xn--p1ai", "www.xn--80aaachc8cmu1au8c1f.xn--p1ai", '
        '"localhost", "127.0.0.1", "testserver"]'
    )
    docs_enabled: bool = False

    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/gate_app"

    secret_key: str = "change-me"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 30

    # v1 login/password bootstrap account
    demo_login: str = "demo"
    demo_password: str = "demo123"
    demo_phone: str = "+70000000000"
    demo_full_name: str = "\u0414\u0435\u043c\u043e \u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c"
    demo_plot_number: str = "25"
    bootstrap_demo_user: bool = True

    # Gate integration controls
    gate_real_integration_enabled: bool = False
    gate_open_mode: str = "simulate"
    gate_open_success_rate: float = 0.9
    gate_python_launcher: str = "py"
    gate_python_version: str = "-3.12-32"
    gate_bridge_timeout_seconds: int = 20
    gate_action_map_json: str = Field(
        default='{"entry": 1, "exit": 2, "wicket_north": 3, "wicket_lake": 4, "wicket_admin": 5, "wicket_forest": 6}'
    )
    default_access_point_ids_json: str = "[1, 2, 3, 4, 5, 6]"
    courier_ttl_only_enabled: bool = True
    courier_default_hours: int = 2
    courier_max_hours: int = 12
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 300

    @property
    def gate_action_map(self) -> dict[str, int]:
        raw = json.loads(self.gate_action_map_json)
        return {str(key): int(value) for key, value in raw.items()}

    @property
    def default_access_point_ids(self) -> list[int]:
        raw = json.loads(self.default_access_point_ids_json)
        return [int(value) for value in raw]

    @property
    def cors_allow_origins(self) -> list[str]:
        raw = json.loads(self.cors_allow_origins_json)
        return [str(value).strip() for value in raw if str(value).strip()]

    @property
    def allowed_hosts(self) -> list[str]:
        raw = json.loads(self.allowed_hosts_json)
        return [str(value).strip() for value in raw if str(value).strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
