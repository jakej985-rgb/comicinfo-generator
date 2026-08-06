import sys
import os
import argparse
from config import load_config, init_config
from cache.db import CacheManager
from automation.queue import ProcessingQueue
from automation.watcher import LibraryWatcher
from providers.kapowarr import KapowarrProvider
from providers.comicvine import ComicVineProvider
from providers.gcp import GCPProvider

def print_banner():
    print("==================================================")
    print(" ComicInfo Generator v2.0 (CLI & Automation Engine)")
    print(" Providers: Kapowarr • ComicVine • Grand Comics Database (GCP)")
    print("==================================================")

def handle_config_init(args):
    path = init_config(force=getattr(args, "force", False))
    print(f"✅ Created default configuration file at: '{path}'")

def handle_generate(args, cfg):
    target = getattr(args, "target", "") or ""
    if not target:
        print("Error: Target file or folder path required.")
        sys.exit(1)

    url_override = getattr(args, "url", "") or ""
    target_abs = os.path.abspath(target)
    
    if not os.path.exists(target_abs):
        print(f"Error: Path '{target}' does not exist.")
        sys.exit(1)

    q = ProcessingQueue(cfg)
    q.start()

    if os.path.isdir(target_abs):
        print(f"📂 Scanning folder: '{target_abs}'...")
        items = q.enqueue_folder(target_abs, recursive=not getattr(args, "no_recursive", False))
        print(f"Enqueued {len(items)} comic files for processing.")
    else:
        print(f"📄 Processing file: '{target_abs}'...")
        q.enqueue_file(target_abs, url_override=url_override)

    q.wait_completion()
    q.stop()
    print("✅ Generation complete.")

def handle_watch(args, cfg):
    folder = getattr(args, "folder", "") or cfg.automation.watch_folder or os.getcwd()
    watcher = LibraryWatcher(cfg)
    watcher.start_watching(folder)

def handle_repair(args, cfg):
    target = getattr(args, "target", "") or os.getcwd()
    target_abs = os.path.abspath(target)
    print(f"🔧 Repair Mode: Scanning '{target_abs}' for missing or corrupted ComicInfo.xml files...")
    
    # Overwrite force option
    cfg.output.overwrite = True
    q = ProcessingQueue(cfg)
    q.start()
    q.enqueue_folder(target_abs, recursive=True)
    q.wait_completion()
    q.stop()
    print("✅ Library Repair complete.")

def handle_cache(args, cfg):
    action = getattr(args, "action", "stats")
    cache_mgr = CacheManager(cfg.cache.db_path)
    
    if action == "clear":
        cache_mgr.clear()
        print("🗑️ SQLite cache and hash tracker cleared successfully.")
    else:
        stats = cache_mgr.get_stats()
        print("📊 SQLite Cache Statistics:")
        print(f"  Database Path:           {stats['db_path']}")
        print(f"  Processed Files Tracked: {stats['processed_files_tracked']}")
        print(f"  Issues Cached:           {stats['issues_cached']}")
        print(f"  Series Cached:           {stats['series_cached']}")
        print(f"  Searches Cached:         {stats['searches_cached']}")

def handle_provider_test(args, cfg):
    print("🔍 Testing Metadata Providers Connectivity...")
    kap = KapowarrProvider(url=cfg.kapowarr.url, api_key=cfg.kapowarr.api_key)
    cv = ComicVineProvider(api_key=cfg.comicvine.api_key)
    gcp = GCPProvider()

    print(f"  Kapowarr ({cfg.kapowarr.url}):   {'✅ Online' if kap.test_connection() else '❌ Offline / Unreachable'}")
    print(f"  ComicVine (CV):                   {'✅ Ready' if cv.get_name() else '❌ Error'}")
    print(f"  Grand Comics Database (GCP):      {'✅ Ready' if gcp.get_name() else '❌ Error'}")

def handle_kapowarr_sync(args, cfg):
    print(f"🔄 Syncing monitored series from Kapowarr ({cfg.kapowarr.url})...")
    kap = KapowarrProvider(url=cfg.kapowarr.url, api_key=cfg.kapowarr.api_key)
    if not kap.test_connection():
        print(f"❌ Error: Cannot connect to Kapowarr server at '{cfg.kapowarr.url}'. Check your configuration.")
        sys.exit(1)

    series_list = kap.search_series("")
    print(f"Found {len(series_list)} monitored series in Kapowarr.")
    print("✅ Sync complete.")

def run_cli():
    print_banner()

    parser = argparse.ArgumentParser(prog="comicinfo", description="ComicInfo Generator v2.0 CLI Tool")
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # config init
    p_cfg = subparsers.add_parser("config", help="Configuration file management")
    p_cfg_sub = p_cfg.add_subparsers(dest="config_action")
    p_cfg_init = p_cfg_sub.add_parser("init", help="Generate default config.yaml")
    p_cfg_init.add_argument("--force", action="store_true", help="Overwrite existing config file")

    # generate
    p_gen = subparsers.add_parser("generate", help="Generate ComicInfo.xml for file or folder")
    p_gen.add_argument("target", nargs="?", help="Path to .cbz/.cbr file or folder")
    p_gen.add_argument("--url", help="Database URL override")
    p_gen.add_argument("--overwrite", action="store_true", help="Overwrite existing ComicInfo.xml")
    p_gen.add_argument("--workers", type=int, help="Number of parallel workers")

    # watch
    p_watch = subparsers.add_parser("watch", help="Watch library directory for new comics")
    p_watch.add_argument("folder", nargs="?", help="Folder directory to watch")

    # repair
    p_repair = subparsers.add_parser("repair", help="Repair and regenerate missing ComicInfo.xml files in library")
    p_repair.add_argument("target", nargs="?", help="Folder directory to repair")

    # cache
    p_cache = subparsers.add_parser("cache", help="Cache management")
    p_cache.add_argument("action", choices=["stats", "clear"], nargs="?", default="stats", help="stats | clear")

    # provider test
    p_prov = subparsers.add_parser("provider", help="Test metadata providers")
    p_prov_sub = p_prov.add_subparsers(dest="provider_action")
    p_prov_test = p_prov_sub.add_parser("test", help="Test provider connectivity")

    # kapowarr sync
    p_kap = subparsers.add_parser("kapowarr", help="Kapowarr integration commands")
    p_kap_sub = p_kap.add_subparsers(dest="kapowarr_action")
    p_kap_sync = p_kap_sub.add_parser("sync", help="Sync monitored series from Kapowarr")

    args = parser.parse_args()

    cli_overrides = {}
    if hasattr(args, "workers") and args.workers is not None:
        cli_overrides["workers"] = args.workers
    if hasattr(args, "overwrite") and args.overwrite:
        cli_overrides["overwrite"] = True

    cfg = load_config(cli_overrides=cli_overrides)

    if args.command == "config" or (len(sys.argv) > 1 and sys.argv[1] == "config"):
        handle_config_init(args)
    elif args.command == "generate":
        handle_generate(args, cfg)
    elif args.command == "watch":
        handle_watch(args, cfg)
    elif args.command == "repair":
        handle_repair(args, cfg)
    elif args.command == "cache":
        handle_cache(args, cfg)
    elif args.command == "provider":
        handle_provider_test(args, cfg)
    elif args.command == "kapowarr":
        handle_kapowarr_sync(args, cfg)
    else:
        parser.print_help()

if __name__ == "__main__":
    run_cli()
