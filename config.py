import os
import sys
import yaml
from dataclasses import dataclass, field
from typing import Optional

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.comicinfo/config.yaml")

DEFAULT_CONFIG_YAML = """# ComicInfo Generator v2 Configuration

comicvine:
  api_key: ""

kapowarr:
  url: "http://localhost:5656"
  api_key: ""

library:
  roots: []
  recursive: true

providers:
  priority:
    - kapowarr
    - comicvine
    - gcd

automation:
  mode: "batch"  # batch
  workers: 4
  prefer_kapowarr: false

cache:
  enabled: true
  db_path: "~/.comicinfo/cache.db"

output:
  embed_xml: true
  overwrite: false
  delete_cbr: true

server:
  host: "127.0.0.1"
  port: 5005
  cors_origins:
    - "http://localhost:5005"
    - "http://127.0.0.1:5005"

logging:
  level: "INFO"
  log_file: "~/.comicinfo/generator.log"
"""

@dataclass
class LibraryConfig:
    roots: list = field(default_factory=list)
    recursive: bool = True

@dataclass
class ProvidersConfig:
    priority: list = field(default_factory=lambda: ["kapowarr", "comicvine", "gcd"])

@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 5005
    cors_origins: list = field(default_factory=lambda: [
        "http://localhost:5005",
        "http://127.0.0.1:5005"
    ])

@dataclass
class ComicvineConfig:
    api_key: str = ""

@dataclass
class KapowarrConfig:
    url: str = "http://localhost:5656"
    api_key: str = ""

@dataclass
class AutomationConfig:
    mode: str = "batch"
    workers: int = 4
    prefer_kapowarr: bool = False

@dataclass
class CacheConfig:
    enabled: bool = True
    db_path: str = os.path.expanduser("~/.comicinfo/cache.db")

@dataclass
class OutputConfig:
    embed_xml: bool = True
    overwrite: bool = False
    delete_cbr: bool = True
    strict_archive_verification: bool = False

@dataclass
class LoggingConfig:
    level: str = "INFO"
    log_file: str = os.path.expanduser("~/.comicinfo/generator.log")

class ConfigurationError(Exception):
    """Raised when configuration values are invalid or unusable for production."""
    pass


def mask_secret(secret: str, show_chars: int = 4) -> str:
    """
    Phase 71.4: Masks sensitive secrets for secure logging.
    Example: '1234567890abcdef' -> '1234...cdef'
    """
    if not secret:
        return "<not set>"
    if len(secret) <= show_chars * 2:
        return "********"
    return f"{secret[:show_chars]}...{secret[-show_chars:]}"


def check_conversion_tools() -> dict:
    """Phase 71.2: Checks availability of conversion utilities (unrar, rar, 7z)."""
    import shutil
    return {
        "unrar": shutil.which("unrar") is not None,
        "rar": shutil.which("rar") is not None,
        "7z": shutil.which("7z") is not None or shutil.which("7za") is not None
    }


def validate_startup_config(cfg: "Config") -> list:
    """
    Phase 71.2, 71.5 & Phase 81: Validates production configuration settings.
    Raises ConfigurationError on fatal misconfigurations and returns informative warnings.
    """
    warnings = []

    # 1. Fatal: Validate Kapowarr URL
    if cfg.kapowarr.url and cfg.kapowarr.url.strip():
        url = cfg.kapowarr.url.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ConfigurationError(
                f"Configuration error: Kapowarr URL is invalid ('{url}'). "
                "URL must begin with 'http://' or 'https://'."
            )
    else:
        warnings.append("Warning: Kapowarr URL is not configured. Kapowarr integration will be disabled.")

    # 2. Fatal / Warning: Validate ComicVine API key
    if cfg.comicvine.api_key:
        key = cfg.comicvine.api_key.strip()
        if any(c.isspace() for c in key):
            raise ConfigurationError(
                "Configuration error: ComicVine API key contains invalid whitespace characters."
            )
    else:
        warnings.append("Warning: ComicVine API key is not configured. ComicVine metadata lookup will be disabled.")

    # 3. Fatal: Validate Workers
    if not isinstance(cfg.automation.workers, int) or cfg.automation.workers < 1:
        raise ConfigurationError(
            f"Configuration error: automation.workers must be an integer >= 1 (got {cfg.automation.workers})."
        )

    # 4. Fatal: Validate Server Config
    if not cfg.server.host or not cfg.server.host.strip():
        raise ConfigurationError("Configuration error: server.host cannot be empty.")
    if not isinstance(cfg.server.port, int) or not (1 <= cfg.server.port <= 65535):
        raise ConfigurationError(
            f"Configuration error: server.port must be an integer between 1 and 65535 (got {cfg.server.port})."
        )
    if not isinstance(cfg.server.cors_origins, list):
        raise ConfigurationError("Configuration error: server.cors_origins must be a list of allowed origins.")

    # 5. Fatal: Validate Logging Level
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if not isinstance(cfg.logging.level, str) or cfg.logging.level.upper() not in valid_levels:
        raise ConfigurationError(
            f"Configuration error: Invalid log level '{cfg.logging.level}'. Must be one of {sorted(valid_levels)}."
        )

    # 6. Fatal: Validate Database & Cache directory writability
    if cfg.cache.enabled and cfg.cache.db_path and cfg.cache.db_path != ":memory:":
        db_dir = os.path.dirname(os.path.abspath(os.path.expanduser(cfg.cache.db_path)))
        if db_dir:
            try:
                os.makedirs(db_dir, exist_ok=True)
                if not os.access(db_dir, os.W_OK):
                    raise ConfigurationError(
                        f"Configuration error: Cache database directory '{db_dir}' is not writable."
                    )
            except Exception as e:
                if isinstance(e, ConfigurationError):
                    raise e
                raise ConfigurationError(
                    f"Configuration error: Cannot create or access cache database directory '{db_dir}': {e}"
                )

    # 7. Warning: Check conversion tool readiness
    tools = check_conversion_tools()
    if not any(tools.values()):
        warnings.append(
            "Warning: No CBR extraction tool (unrar/rar/7z) found on PATH. CBR conversion will be unavailable."
        )

    return warnings


@dataclass
class Config:
    comicvine: ComicvineConfig = field(default_factory=ComicvineConfig)
    kapowarr: KapowarrConfig = field(default_factory=KapowarrConfig)
    providers: ProvidersConfig = field(default_factory=ProvidersConfig)
    library: LibraryConfig = field(default_factory=LibraryConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    automation: AutomationConfig = field(default_factory=AutomationConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    config_file_path: str = DEFAULT_CONFIG_PATH

    def to_safe_dict(self) -> dict:
        """
        Phase 71.4 & Phase 80.1: Returns a dictionary representation of configuration
        with sensitive secrets (API keys) securely masked.
        """
        return {
            "comicvine": {
                "api_key": mask_secret(self.comicvine.api_key),
                "api_key_set": bool(self.comicvine.api_key and self.comicvine.api_key.strip())
            },
            "kapowarr": {
                "url": self.kapowarr.url,
                "api_key": mask_secret(self.kapowarr.api_key),
                "api_key_set": bool(self.kapowarr.api_key and self.kapowarr.api_key.strip())
            },
            "providers": {
                "priority": list(self.providers.priority)
            },
            "library": {
                "roots": list(self.library.roots),
                "recursive": self.library.recursive
            },
            "server": {
                "host": self.server.host,
                "port": self.server.port,
                "cors_origins": list(self.server.cors_origins)
            },
            "automation": {
                "mode": self.automation.mode,
                "workers": self.automation.workers,
                "prefer_kapowarr": self.automation.prefer_kapowarr
            },
            "cache": {
                "enabled": self.cache.enabled,
                "db_path": self.cache.db_path
            },
            "output": {
                "embed_xml": self.output.embed_xml,
                "overwrite": self.output.overwrite,
                "delete_cbr": self.output.delete_cbr,
                "strict_archive_verification": self.output.strict_archive_verification
            },
            "logging": {
                "level": self.logging.level,
                "log_file": self.logging.log_file
            },
            "config_file_path": self.config_file_path
        }


def init_config(config_path: str = DEFAULT_CONFIG_PATH, force: bool = False) -> str:
    """Generates default config.yaml file if it does not already exist."""
    expanded_path = os.path.expanduser(config_path)
    if os.path.exists(expanded_path) and not force:
        return expanded_path

    os.makedirs(os.path.dirname(expanded_path), exist_ok=True)
    with open(expanded_path, "w", encoding="utf-8") as f:
        f.write(DEFAULT_CONFIG_YAML)
    return expanded_path


def _parse_bool(val, field_name: str) -> bool:
    """Safely converts boolean-like values, handling strings and booleans."""
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        lowered = val.strip().lower()
        if lowered in ("true", "1", "yes", "on"):
            return True
        if lowered in ("false", "0", "no", "off"):
            return False
    raise ConfigurationError(f"Configuration error: {field_name} must be a boolean (got '{val}').")


def _parse_int(val, field_name: str, min_val: Optional[int] = None, max_val: Optional[int] = None) -> int:
    """Safely parses integers with bounds checking and clean error messages."""
    try:
        parsed = int(val)
    except (ValueError, TypeError):
        raise ConfigurationError(f"Configuration error: {field_name} must be an integer (got '{val}').")
    if min_val is not None and parsed < min_val:
        raise ConfigurationError(f"Configuration error: {field_name} must be >= {min_val} (got {parsed}).")
    if max_val is not None and parsed > max_val:
        raise ConfigurationError(f"Configuration error: {field_name} must be <= {max_val} (got {parsed}).")
    return parsed


def load_config(
    config_path: Optional[str] = None,
    cli_overrides: Optional[dict] = None,
    validate: bool = False
) -> Config:
    """
    Phase 71 & Phase 81: Loads configuration with resolution precedence:
    CLI Overrides > Environment Variables > config.yaml > Default Values

    Guarantees controlled type conversions, clean ConfigurationError on invalid values,
    and optional mandatory startup validation.
    """
    target_path = config_path or os.environ.get("COMICINFO_CONFIG") or DEFAULT_CONFIG_PATH
    expanded_path = os.path.expanduser(target_path)

    yaml_data = {}
    if os.path.exists(expanded_path):
        try:
            with open(expanded_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if loaded is not None:
                    if not isinstance(loaded, dict):
                        raise ConfigurationError(
                            f"Configuration error: Config file '{expanded_path}' must be a YAML mapping/dictionary."
                        )
                    yaml_data = loaded
        except yaml.YAMLError as ye:
            raise ConfigurationError(f"Configuration error: Malformed YAML in '{expanded_path}': {ye}")
        except ConfigurationError:
            raise
        except Exception as e:
            sys.stderr.write(f"Warning: Failed to parse config file '{expanded_path}': {e}\n")

    cfg = Config(config_file_path=expanded_path)

    # 1. Parse YAML values
    cv_yaml = yaml_data.get("comicvine", {})
    if isinstance(cv_yaml, dict):
        cfg.comicvine.api_key = str(cv_yaml.get("api_key", cfg.comicvine.api_key) or "")

    kap_yaml = yaml_data.get("kapowarr", {})
    if isinstance(kap_yaml, dict):
        cfg.kapowarr.url = str(kap_yaml.get("url", cfg.kapowarr.url) or "")
        cfg.kapowarr.api_key = str(kap_yaml.get("api_key", cfg.kapowarr.api_key) or "")

    auto_yaml = yaml_data.get("automation", {})
    if isinstance(auto_yaml, dict):
        cfg.automation.mode = str(auto_yaml.get("mode", cfg.automation.mode) or "batch")
        if "workers" in auto_yaml and auto_yaml["workers"] is not None:
            cfg.automation.workers = _parse_int(auto_yaml["workers"], "automation.workers", min_val=1)
        if "prefer_kapowarr" in auto_yaml and auto_yaml["prefer_kapowarr"] is not None:
            cfg.automation.prefer_kapowarr = _parse_bool(auto_yaml["prefer_kapowarr"], "automation.prefer_kapowarr")

    lib_yaml = yaml_data.get("library", {})
    if isinstance(lib_yaml, dict):
        if "roots" in lib_yaml and isinstance(lib_yaml["roots"], list):
            cfg.library.roots = [os.path.expanduser(str(r)) for r in lib_yaml["roots"] if r]
        if "recursive" in lib_yaml and lib_yaml["recursive"] is not None:
            cfg.library.recursive = _parse_bool(lib_yaml["recursive"], "library.recursive")

    prov_yaml = yaml_data.get("providers", {})
    if isinstance(prov_yaml, dict):
        if "priority" in prov_yaml and isinstance(prov_yaml["priority"], list):
            cfg.providers.priority = [str(p).lower().strip() for p in prov_yaml["priority"]]

    srv_yaml = yaml_data.get("server", {})
    if isinstance(srv_yaml, dict):
        cfg.server.host = str(srv_yaml.get("host", cfg.server.host) or "127.0.0.1")
        if "port" in srv_yaml and srv_yaml["port"] is not None:
            cfg.server.port = _parse_int(srv_yaml["port"], "server.port", min_val=1, max_val=65535)
        if "cors_origins" in srv_yaml and srv_yaml["cors_origins"] is not None:
            if not isinstance(srv_yaml["cors_origins"], list):
                raise ConfigurationError("Configuration error: server.cors_origins must be a list of allowed origins.")
            cfg.server.cors_origins = [str(o) for o in srv_yaml["cors_origins"]]

    cache_yaml = yaml_data.get("cache", {})
    if isinstance(cache_yaml, dict):
        if "enabled" in cache_yaml and cache_yaml["enabled"] is not None:
            cfg.cache.enabled = _parse_bool(cache_yaml["enabled"], "cache.enabled")
        if "db_path" in cache_yaml and cache_yaml["db_path"]:
            cfg.cache.db_path = os.path.expanduser(str(cache_yaml["db_path"]))

    out_yaml = yaml_data.get("output", {})
    if isinstance(out_yaml, dict):
        if "embed_xml" in out_yaml and out_yaml["embed_xml"] is not None:
            cfg.output.embed_xml = _parse_bool(out_yaml["embed_xml"], "output.embed_xml")
        if "overwrite" in out_yaml and out_yaml["overwrite"] is not None:
            cfg.output.overwrite = _parse_bool(out_yaml["overwrite"], "output.overwrite")
        if "delete_cbr" in out_yaml and out_yaml["delete_cbr"] is not None:
            cfg.output.delete_cbr = _parse_bool(out_yaml["delete_cbr"], "output.delete_cbr")
        if "strict_archive_verification" in out_yaml and out_yaml["strict_archive_verification"] is not None:
            cfg.output.strict_archive_verification = _parse_bool(out_yaml["strict_archive_verification"], "output.strict_archive_verification")

    log_yaml = yaml_data.get("logging", {})
    if isinstance(log_yaml, dict):
        if "level" in log_yaml and log_yaml["level"]:
            cfg.logging.level = str(log_yaml["level"]).upper()
        if "log_file" in log_yaml and log_yaml["log_file"]:
            cfg.logging.log_file = os.path.expanduser(str(log_yaml["log_file"]))

    # 2. Parse Environment Variables (Overrides YAML if non-empty)
    if os.environ.get("COMICVINE_API_KEY") is not None and os.environ.get("COMICVINE_API_KEY").strip() != "":
        cfg.comicvine.api_key = os.environ["COMICVINE_API_KEY"].strip()
    if os.environ.get("KAPOWARR_URL") is not None and os.environ.get("KAPOWARR_URL").strip() != "":
        cfg.kapowarr.url = os.environ["KAPOWARR_URL"].strip()
    if os.environ.get("KAPOWARR_API_KEY") is not None and os.environ.get("KAPOWARR_API_KEY").strip() != "":
        cfg.kapowarr.api_key = os.environ["KAPOWARR_API_KEY"].strip()
    if os.environ.get("COMICINFO_LIBRARY_ROOTS") is not None and os.environ.get("COMICINFO_LIBRARY_ROOTS").strip() != "":
        cfg.library.roots = [os.path.expanduser(r.strip()) for r in os.environ["COMICINFO_LIBRARY_ROOTS"].split(",") if r.strip()]
    if os.environ.get("COMICINFO_PROVIDER_PRIORITY") is not None and os.environ.get("COMICINFO_PROVIDER_PRIORITY").strip() != "":
        cfg.providers.priority = [p.strip().lower() for p in os.environ["COMICINFO_PROVIDER_PRIORITY"].split(",") if p.strip()]
    if os.environ.get("COMICINFO_HOST") is not None and os.environ.get("COMICINFO_HOST").strip() != "":
        cfg.server.host = os.environ["COMICINFO_HOST"].strip()
    if os.environ.get("COMICINFO_PORT") is not None and os.environ.get("COMICINFO_PORT").strip() != "":
        cfg.server.port = _parse_int(os.environ["COMICINFO_PORT"], "COMICINFO_PORT", min_val=1, max_val=65535)
    if os.environ.get("COMICINFO_CORS_ORIGINS") is not None and os.environ.get("COMICINFO_CORS_ORIGINS").strip() != "":
        cfg.server.cors_origins = [o.strip() for o in os.environ["COMICINFO_CORS_ORIGINS"].split(",") if o.strip()]
    if os.environ.get("COMICINFO_WORKERS") is not None and os.environ.get("COMICINFO_WORKERS").strip() != "":
        cfg.automation.workers = _parse_int(os.environ["COMICINFO_WORKERS"], "COMICINFO_WORKERS", min_val=1)
    if os.environ.get("COMICINFO_CACHE_ENABLED") is not None and os.environ.get("COMICINFO_CACHE_ENABLED").strip() != "":
        cfg.cache.enabled = _parse_bool(os.environ["COMICINFO_CACHE_ENABLED"], "COMICINFO_CACHE_ENABLED")
    if os.environ.get("COMICINFO_LOG_LEVEL") is not None and os.environ.get("COMICINFO_LOG_LEVEL").strip() != "":
        cfg.logging.level = os.environ["COMICINFO_LOG_LEVEL"].strip().upper()
    if os.environ.get("COMICINFO_STRICT_ARCHIVE_VERIFICATION") is not None and os.environ.get("COMICINFO_STRICT_ARCHIVE_VERIFICATION").strip() != "":
        cfg.output.strict_archive_verification = _parse_bool(os.environ["COMICINFO_STRICT_ARCHIVE_VERIFICATION"], "COMICINFO_STRICT_ARCHIVE_VERIFICATION")

    # 3. Parse CLI Overrides (Overrides Environment & YAML)
    if cli_overrides:
        if "library_roots" in cli_overrides and cli_overrides["library_roots"] is not None:
            roots = cli_overrides["library_roots"]
            if isinstance(roots, str):
                cfg.library.roots = [os.path.expanduser(r.strip()) for r in roots.split(",") if r.strip()]
            elif isinstance(roots, list):
                cfg.library.roots = [os.path.expanduser(str(r)) for r in roots if r]
        if "recursive" in cli_overrides and cli_overrides["recursive"] is not None:
            cfg.library.recursive = _parse_bool(cli_overrides["recursive"], "CLI recursive override")
        if "comicvine_api_key" in cli_overrides and cli_overrides["comicvine_api_key"] is not None:
            cfg.comicvine.api_key = str(cli_overrides["comicvine_api_key"])
        if "kapowarr_url" in cli_overrides and cli_overrides["kapowarr_url"] is not None:
            cfg.kapowarr.url = str(cli_overrides["kapowarr_url"])
        if "kapowarr_api_key" in cli_overrides and cli_overrides["kapowarr_api_key"] is not None:
            cfg.kapowarr.api_key = str(cli_overrides["kapowarr_api_key"])
        if "host" in cli_overrides and cli_overrides["host"] is not None:
            cfg.server.host = str(cli_overrides["host"])
        if "port" in cli_overrides and cli_overrides["port"] is not None:
            cfg.server.port = _parse_int(cli_overrides["port"], "CLI port override", min_val=1, max_val=65535)
        if "cors_origins" in cli_overrides and cli_overrides["cors_origins"] is not None:
            if not isinstance(cli_overrides["cors_origins"], list):
                raise ConfigurationError("Configuration error: CLI cors_origins must be a list of allowed origins.")
            cfg.server.cors_origins = list(cli_overrides["cors_origins"])
        if "workers" in cli_overrides and cli_overrides["workers"] is not None:
            cfg.automation.workers = _parse_int(cli_overrides["workers"], "CLI workers override", min_val=1)
        if "overwrite" in cli_overrides and cli_overrides["overwrite"] is not None:
            cfg.output.overwrite = _parse_bool(cli_overrides["overwrite"], "CLI overwrite override")
        if "strict_archive_verification" in cli_overrides and cli_overrides["strict_archive_verification"] is not None:
            cfg.output.strict_archive_verification = _parse_bool(cli_overrides["strict_archive_verification"], "CLI strict_archive_verification override")
        if "log_level" in cli_overrides and cli_overrides["log_level"] is not None:
            cfg.logging.level = str(cli_overrides["log_level"]).upper()

    if validate:
        validate_startup_config(cfg)

    return cfg


def discover_library_files(cfg: Config) -> list:
    """
    Phase 88.1: Discovers comic archive files (.cbz, .cbr) across configured library.roots
    without any hardcoded paths or environment-specific assumptions.
    """
    discovered = []
    seen = set()
    for root in cfg.library.roots:
        expanded = os.path.abspath(os.path.expanduser(root))
        if not os.path.exists(expanded):
            continue
        if os.path.isfile(expanded):
            if expanded.lower().endswith((".cbz", ".cbr")) and expanded not in seen:
                seen.add(expanded)
                discovered.append(expanded)
        elif os.path.isdir(expanded):
            if cfg.library.recursive:
                for dirpath, _, filenames in os.walk(expanded):
                    for f in sorted(filenames):
                        if f.lower().endswith((".cbz", ".cbr")):
                            full = os.path.join(dirpath, f)
                            if full not in seen:
                                seen.add(full)
                                discovered.append(full)
            else:
                for f in sorted(os.listdir(expanded)):
                    if f.lower().endswith((".cbz", ".cbr")):
                        full = os.path.join(expanded, f)
                        if full not in seen:
                            seen.add(full)
                            discovered.append(full)
    return discovered

