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

automation:
  mode: "batch"  # batch | watch
  workers: 4
  watch_folder: ""
  prefer_kapowarr: false

cache:
  enabled: true
  db_path: "~/.comicinfo/cache.db"

output:
  embed_xml: true
  overwrite: false
  delete_cbr: true

logging:
  level: "INFO"
  log_file: "~/.comicinfo/generator.log"
"""

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
    watch_folder: str = ""
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

@dataclass
class LoggingConfig:
    level: str = "INFO"
    log_file: str = os.path.expanduser("~/.comicinfo/generator.log")

@dataclass
class Config:
    comicvine: ComicvineConfig = field(default_factory=ComicvineConfig)
    kapowarr: KapowarrConfig = field(default_factory=KapowarrConfig)
    automation: AutomationConfig = field(default_factory=AutomationConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    config_file_path: str = DEFAULT_CONFIG_PATH

def init_config(config_path: str = DEFAULT_CONFIG_PATH, force: bool = False) -> str:
    """Generates default config.yaml file if it does not already exist."""
    expanded_path = os.path.expanduser(config_path)
    if os.path.exists(expanded_path) and not force:
        return expanded_path

    os.makedirs(os.path.dirname(expanded_path), exist_ok=True)
    with open(expanded_path, "w", encoding="utf-8") as f:
        f.write(DEFAULT_CONFIG_YAML)
    return expanded_path

def load_config(config_path: Optional[str] = None, cli_overrides: Optional[dict] = None) -> Config:
    """
    Loads configuration with resolution precedence:
    CLI Overrides > Environment Variables > config.yaml > Default Values
    """
    target_path = config_path or os.environ.get("COMICINFO_CONFIG") or DEFAULT_CONFIG_PATH
    expanded_path = os.path.expanduser(target_path)

    yaml_data = {}
    if os.path.exists(expanded_path):
        try:
            with open(expanded_path, "r", encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f) or {}
        except Exception as e:
            sys.stderr.write(f"Warning: Failed to parse config file '{expanded_path}': {e}\n")

    cfg = Config(config_file_path=expanded_path)

    # 1. Parse YAML values
    cv_yaml = yaml_data.get("comicvine", {})
    cfg.comicvine.api_key = str(cv_yaml.get("api_key", cfg.comicvine.api_key) or "")

    kap_yaml = yaml_data.get("kapowarr", {})
    cfg.kapowarr.url = str(kap_yaml.get("url", cfg.kapowarr.url) or "")
    cfg.kapowarr.api_key = str(kap_yaml.get("api_key", cfg.kapowarr.api_key) or "")

    auto_yaml = yaml_data.get("automation", {})
    cfg.automation.mode = str(auto_yaml.get("mode", cfg.automation.mode) or "batch")
    cfg.automation.workers = int(auto_yaml.get("workers", cfg.automation.workers) or 4)
    cfg.automation.watch_folder = str(auto_yaml.get("watch_folder", cfg.automation.watch_folder) or "")
    cfg.automation.prefer_kapowarr = bool(auto_yaml.get("prefer_kapowarr", False))

    cache_yaml = yaml_data.get("cache", {})
    cfg.cache.enabled = bool(cache_yaml.get("enabled", cfg.cache.enabled))
    if "db_path" in cache_yaml and cache_yaml["db_path"]:
        cfg.cache.db_path = os.path.expanduser(str(cache_yaml["db_path"]))

    out_yaml = yaml_data.get("output", {})
    cfg.output.embed_xml = bool(out_yaml.get("embed_xml", cfg.output.embed_xml))
    cfg.output.overwrite = bool(out_yaml.get("overwrite", cfg.output.overwrite))
    cfg.output.delete_cbr = bool(out_yaml.get("delete_cbr", cfg.output.delete_cbr))

    log_yaml = yaml_data.get("logging", {})
    cfg.logging.level = str(log_yaml.get("level", cfg.logging.level) or "INFO").upper()
    if "log_file" in log_yaml and log_yaml["log_file"]:
        cfg.logging.log_file = os.path.expanduser(str(log_yaml["log_file"]))

    # 2. Parse Environment Variables (Overrides YAML)
    if os.environ.get("COMICVINE_API_KEY"):
        cfg.comicvine.api_key = os.environ["COMICVINE_API_KEY"]
    if os.environ.get("KAPOWARR_URL"):
        cfg.kapowarr.url = os.environ["KAPOWARR_URL"]
    if os.environ.get("KAPOWARR_API_KEY"):
        cfg.kapowarr.api_key = os.environ["KAPOWARR_API_KEY"]
    if os.environ.get("COMICINFO_WORKERS"):
        try:
            cfg.automation.workers = int(os.environ["COMICINFO_WORKERS"])
        except ValueError:
            pass
    if os.environ.get("COMICINFO_CACHE_ENABLED"):
        cfg.cache.enabled = os.environ["COMICINFO_CACHE_ENABLED"].lower() in ("true", "1", "yes")
    if os.environ.get("COMICINFO_LOG_LEVEL"):
        cfg.logging.level = os.environ["COMICINFO_LOG_LEVEL"].upper()

    # 3. Parse CLI Overrides (Overrides Environment & YAML)
    if cli_overrides:
        if "comicvine_api_key" in cli_overrides and cli_overrides["comicvine_api_key"] is not None:
            cfg.comicvine.api_key = str(cli_overrides["comicvine_api_key"])
        if "kapowarr_url" in cli_overrides and cli_overrides["kapowarr_url"] is not None:
            cfg.kapowarr.url = str(cli_overrides["kapowarr_url"])
        if "kapowarr_api_key" in cli_overrides and cli_overrides["kapowarr_api_key"] is not None:
            cfg.kapowarr.api_key = str(cli_overrides["kapowarr_api_key"])
        if "workers" in cli_overrides and cli_overrides["workers"] is not None:
            cfg.automation.workers = int(cli_overrides["workers"])
        if "overwrite" in cli_overrides and cli_overrides["overwrite"] is not None:
            cfg.output.overwrite = bool(cli_overrides["overwrite"])
        if "log_level" in cli_overrides and cli_overrides["log_level"] is not None:
            cfg.logging.level = str(cli_overrides["log_level"]).upper()

    return cfg
