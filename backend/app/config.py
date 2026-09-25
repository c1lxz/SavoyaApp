from __future__ import annotations

import json
from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .utils.input_safety import normalize_strong_password


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"
    app_name: str = "GateApp Backend"
    debug: bool = False
    api_prefix: str = "/api"
    cors_allow_origins_json: str = (
        '["https://ipksavoya.ru", "https://www.ipksavoya.ru", "http://localhost", "http://127.0.0.1", '
        '"http://localhost:80", "http://127.0.0.1:80", "http://localhost:8081", "http://127.0.0.1:8081", '
        '"http://localhost:8082", "http://127.0.0.1:8082", "http://localhost:8083", "http://127.0.0.1:8083", '
        '"http://localhost:19006", "http://127.0.0.1:19006"]'
    )
    allowed_hosts_json: str = '["ipksavoya.ru", "www.ipksavoya.ru", "localhost", "127.0.0.1", "testserver"]'
    docs_enabled: bool = False

    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/gate_app"

    # Keep this directory on persistent storage, outside the public frontend tree.
    news_media_dir: str = "./data/news-media"
    news_max_upload_bytes: int = Field(default=100 * 1024 * 1024, ge=1024, le=1024 * 1024 * 1024)
    news_media_url_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    news_unattached_ttl_hours: int = Field(default=24, ge=1)
    news_max_unattached_uploads: int = Field(default=30, ge=10, le=1000)
    news_worker_enabled: bool = True
    news_device_ttl_days: int = Field(default=30, ge=1, le=365)
    news_fcm_service_account_file: str = ""
    news_fcm_project_id: str = ""

    secret_key: str = "change-me"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 365
    jwt_issuer: str = "savoya-backend"
    jwt_audience: str = "savoya-clients"

    # v1 login/password bootstrap account
    demo_login: str = "demo"
    demo_password: str = "demo123"
    demo_phone: str = "+70000000000"
    demo_full_name: str = "\u0414\u0435\u043c\u043e \u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c"
    demo_plot_number: str = "25"
    bootstrap_demo_user: bool = True
    bootstrap_test_users_json: str = "[]"
    bootstrap_admin_user: bool = False
    admin_login: str = ""
    admin_password: str = ""
    admin_phone: str = "+79990009999"
    admin_full_name: str = "\u0410\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440 Savoya"
    admin_plot_number: str = "ADMIN"

    # Gate integration controls
    gate_real_integration_enabled: bool = False
    gate_open_mode: str = "simulate"
    gate_open_success_rate: float = 0.9
    gate_python_launcher: str = "py"
    gate_python_version: str = "-3.12-32"
    gate_bridge_timeout_seconds: int = 20
    gate_bridge_maintenance_timeout_seconds: int = 300
    gate_bridge_vehicle_post_sync_timeout_seconds: int = 60
    gate_bridge_retry_attempts: int = 3
    gate_bridge_retry_delay_seconds: float = 0.75
    gate_gateterm_users_guard_enabled: bool = False
    gate_vehicle_post_sync_required: bool = True
    gate_startup_sync_enabled: bool = False
    gate_action_map_json: str = Field(
        default='{"entry": 19, "exit": 20, "wicket_north": 15, "wicket_lake": 23, "wicket_admin": 17, "wicket_forest": 21}'
    )
    # Mandatory app-operated access points in the live Savoya Gate database:
    # north wicket, wicket 1, entry/exit cameras, forest and lake wickets.
    default_access_point_ids_json: str = "[15, 17, 19, 20, 21, 23]"
    gsm_access_point_ids_json: str = "[]"
    courier_ttl_only_enabled: bool = True
    courier_default_hours: int = 2
    courier_max_hours: int = 12
    gate_event_poll_enabled: bool = True
    gate_event_poll_interval_seconds: float = 10.0
    gate_event_poll_limit: int = 200
    # Total attempts to provision the Gate phone pass when creating a resident before
    # giving up and rolling the new account back. The bridge also retries internally,
    # so this guards against an intermittent GateTerm UI hiccup losing the whole user.
    gate_phone_link_attempts: int = 3
    gate_background_maintenance_enabled: bool = False
    gate_maintenance_interval_seconds: float = 300.0
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 300
    login_ip_rate_limit_attempts: int = 20
    login_ip_rate_limit_window_seconds: int = 300

    @property
    def gate_action_map(self) -> dict[str, int]:
        raw = json.loads(self.gate_action_map_json)
        return {str(key): int(value) for key, value in raw.items()}

    @property
    def default_access_point_ids(self) -> list[int]:
        raw = json.loads(self.default_access_point_ids_json)
        return [int(value) for value in raw]

    @property
    def gsm_access_point_ids(self) -> list[int]:
        raw = json.loads(self.gsm_access_point_ids_json)
        return [int(value) for value in raw]

    @property
    def cors_allow_origins(self) -> list[str]:
        raw = json.loads(self.cors_allow_origins_json)
        return [str(value).strip() for value in raw if str(value).strip()]

    @property
    def allowed_hosts(self) -> list[str]:
        raw = json.loads(self.allowed_hosts_json)
        return [str(value).strip() for value in raw if str(value).strip()]

    @property
    def bootstrap_test_users(self) -> list[dict[str, str]]:
        raw = json.loads(self.bootstrap_test_users_json)
        users: list[dict[str, str]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            login = str(item.get("login", "")).strip()
            password = str(item.get("password", "")).strip()
            phone = str(item.get("phone", "")).strip()
            if not login or not password or not phone:
                continue
            users.append(
                {
                    "login": login,
                    "password": password,
                    "phone": phone,
                    "name": str(item.get("name", "")).strip(),
                    "plot_number": str(item.get("plot_number", "")).strip(),
                }
            )
        return users

    @property
    def normalized_environment(self) -> str:
        return self.environment.strip().lower() or "development"

    @property
    def is_production(self) -> bool:
        return self.normalized_environment == "production"

    def validate_runtime_security(self) -> None:
        if not self.is_production:
            return

        issues: list[str] = []
        secret_key = self.secret_key.strip()
        if len(secret_key) < 32 or secret_key == "change-me":
            issues.append("SECRET_KEY must be a long random value (minimum 32 characters)")
        if self.debug:
            issues.append("DEBUG must be False in production")
        if self.docs_enabled:
            issues.append("DOCS_ENABLED must be False in production")
        if self.bootstrap_demo_user:
            issues.append("BOOTSTRAP_DEMO_USER must be False in production")
        if self.bootstrap_test_users:
            issues.append("BOOTSTRAP_TEST_USERS_JSON must be empty in production")
        if self.access_token_expire_minutes > 60 * 24 * 365:
            issues.append("ACCESS_TOKEN_EXPIRE_MINUTES must not exceed 525600 in production")
        if "*" in self.allowed_hosts:
            issues.append("ALLOWED_HOSTS_JSON must not contain '*' in production")
        if "*" in self.cors_allow_origins:
            issues.append("CORS_ALLOW_ORIGINS_JSON must not contain '*' in production")
        for origin in self.cors_allow_origins:
            parsed = urlparse(origin)
            hostname = (parsed.hostname or "").lower()
            if hostname in {"localhost", "127.0.0.1", "::1", "testserver"}:
                continue
            if parsed.scheme != "https":
                issues.append(f"CORS origin must use https in production: {origin}")
        if self.bootstrap_admin_user:
            try:
                normalize_strong_password(self.admin_password)
            except ValueError:
                issues.append("ADMIN_PASSWORD must satisfy the strong password policy when BOOTSTRAP_ADMIN_USER=True")
        if self.database_url == "postgresql+asyncpg://user:password@localhost:5432/gate_app":
            issues.append("DATABASE_URL is still using the placeholder value")

        if issues:
            joined = "\n".join(f"- {issue}" for issue in issues)
            raise RuntimeError(f"Insecure production configuration detected:\n{joined}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
