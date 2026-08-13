# 📚 ComicInfo Generator & Tagger

A high-integrity comic archive metadata scraper, resolver, and tagger. Automatically matches comic archives against Comic Vine and Kapowarr, generates standard `ComicInfo.xml` metadata, safely converts `.cbr` archives to `.cbz`, and embeds metadata with atomic write guarantees.

---

## 🌟 Key Capabilities

- **⚡ Identity Resolution & Metadata Decoupling**: Resolving which comic an archive represents (`ComicIdentity`) is strictly decoupled from retrieving the metadata payload (`MetadataRetrievalResult`).
- **🛡️ Multi-Signal Confidence Scoring**: Evaluates candidate matches using series name matching, year tolerance, issue numbering, and publisher agreement. Low confidence results require manual review.
- **🔒 Atomic Archive Write Safety**: Modifications write to a temporary file in the target directory, execute storage `fsync`, verify entry CRC/SHA256 manifests, and atomically replace the archive (`os.replace`).
- **📦 Safe CBR to CBZ Conversion**: Converts RAR/RAR5 `.cbr` files to `.cbz` using `unrar` or `7z`. Original `.cbr` files are preserved until the new `.cbz` passes post-embed verification.
- **🔍 Side-Effect-Free Dry Run**: Full CLI dry-run evaluation mode (`python main.py --dry-run <path>`) evaluating libraries with zero mutations to archives or persistent databases.
- **📊 Modern Web UI**: Responsive dark glassmorphism interface for single-issue tagging, batch folder runs, Trade Paperback (TPB) merging, and story arc cross-referencing.
- **🏷️ Standard ComicInfo.xml Schema**: Tags `<Title>`, `<Series>`, `<Number>`, `<Volume>`, `<Count>`, `<Summary>`, `<Year>`, `<Month>`, `<Day>`, `<Publisher>`, `<Web>`, `<Writer>`, `<Penciller>`, `<Inker>`, `<Colorist>`, `<Letterer>`, `<CoverArtist>`, `<Characters>`, `<Teams>`, `<StoryArc>`, and `<StoryArcNumber>`. Compatible with Kavita, Komga, YACReader, and ComicRack.

---

## 🚀 Getting Started

### 1. Installation

```bash
# Clone repository
git clone https://github.com/jakej985-rgb/comicinfo-generator.git
cd comicinfo-generator

# Create virtual environment and install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Run the Web Application

```bash
python main.py
```

Then open **`http://localhost:5005`** in your browser. (To use a custom port: `python main.py 8080`).

### 3. Evaluate a Library in Dry-Run Mode

```bash
python main.py --dry-run /path/to/comics/
```

---

## 🔍 Dry-Run CLI Evaluation

Dry-run mode inspects files, parses filenames, scores provider candidates, checks metadata completeness, and prints a detailed decision report without writing to disk:

```
=================================================================
 DRY-RUN MODE: Evaluating '/home/user/Comics'
 NO ARCHIVE FILES OR PERSISTENT DATABASES WILL BE MODIFIED
=================================================================

[1/1] Archive:
  Batman #001 (2016).cbz

Identity:
  Series: Batman
  Issue: #1
  Year: 2016

Candidate:
  ComicVine #4000-539097

Confidence:
  95.0% (AUTO_ACCEPT)

Evidence:
  +30 Issue number matched (#1)
  +25 Exact series name matched 'Batman'
  +15 Publication year matched (2016)
  +15 Publisher matched 'DC Comics'

Metadata State:
  METADATA_FOUND

Action:
  AUTO_ACCEPT

Changes:
  - Title
  - Series
  - Number
  - Publisher
  - Year
  - Writer
  - Penciller

=================================================================
 DRY-RUN COMPLETE: 0 files were modified.
=================================================================
```

---

## ⚙️ Configuration

Configuration is loaded with the following precedence:
**CLI Flags > Environment Variables > `~/.comicinfo/config.yaml` > Default Values**

### `config.yaml` Example

```yaml
comicvine:
  api_key: "your-comicvine-api-key"

kapowarr:
  url: "http://localhost:5656"
  api_key: "your-kapowarr-api-key"

automation:
  mode: "batch"
  workers: 4
  prefer_kapowarr: false

cache:
  enabled: true
  db_path: "~/.comicinfo/cache.db"

output:
  embed_xml: true
  overwrite: false
  delete_cbr: true
  strict_archive_verification: false

logging:
  level: "INFO"
  log_file: "~/.comicinfo/generator.log"
```

### Environment Variables

| Variable | Description | Default |
| --- | --- | --- |
| `COMICVINE_API_KEY` | Comic Vine API key for authenticated metadata queries | `""` |
| `KAPOWARR_URL` | Base URL of running Kapowarr instance | `""` |
| `KAPOWARR_API_KEY` | Kapowarr API key | `""` |
| `COMICINFO_CONFIG` | Custom path to `config.yaml` | `~/.comicinfo/config.yaml` |
| `COMICINFO_WORKERS` | Number of parallel worker threads | `4` |
| `COMICINFO_CACHE_ENABLED` | Enable SQLite caching and SHA256 file tracking | `true` |
| `COMICINFO_LOG_LEVEL` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
| `COMICINFO_STRICT_ARCHIVE_VERIFICATION` | Enable byte-level SHA256 verification on untouched entries | `false` |

> [!NOTE]
> Sensitive credentials (API keys and tokens) are automatically masked in all log outputs and config exports.

---

## 🛡️ Safety Guarantees & Architecture

1. **Identity $\ne$ Metadata**: Establishing file identity (`ComicIdentity`) does not guarantee metadata retrieval. If a provider returns `HTTP 500`, `NOT_FOUND`, `PARTIAL`, or `INVALID` metadata, automatic writing is blocked and the archive remains unmodified.
2. **Confidence Thresholds**:
   - $\ge 85$: Auto-accepted if metadata retrieval is complete.
   - $70 - 84$: Manual review recommended; flagged for inspection.
   - $< 70$: Automatic writes strictly prohibited.
3. **Archive Preservation**:
   - Embedding `ComicInfo.xml` preserves all existing image files, page order, directory structure, and non-ComicInfo archive assets.
   - Unrecognized existing XML tags are preserved during re-tagging.
4. **Crash Safety**: All write operations use atomic file replacement with directory `fsync` to prevent archive truncation during power loss or system crashes.

---

## 📁 Repository Structure

```
comicinfo-generator/
├── api/                   # HTTP routing and REST API endpoints (handlers, server)
├── automation/            # Processing queue, background worker threads, file watcher
├── cache/                 # SQLite caching (hash tracking, metadata cache, durable job store)
├── converters/            # CBR to CBZ extraction and repackaging utilities
├── docs/                  # Architectural documentation, invariant specifications, and guides
├── models/                # Domain models (Comic, ComicIdentity, KapowarrVolume, etc.)
├── observability/         # Structured logging, metrics, rate limiter, retry engine
├── pipeline/              # Filename parsing, scoring, confidence engine, resolver, dry-run
├── providers/             # Metadata providers (ComicVine, Kapowarr, GCP/GCD, story arcs)
├── services/              # Business services (archive processing, jobs, settings, story arcs)
├── static/                # Modern Glassmorphism Web UI (HTML, CSS, JavaScript)
├── templates/             # Base HTML templates
├── tests/                 # 306+ comprehensive unit, integration, and fuzz test suites
├── writers/               # Atomic archive writer and ComicInfo.xml generator
├── config.py              # Configuration loader, validation, and secret masking
├── main.py                # Main application CLI (Web Server & --dry-run)
├── requirements.txt       # Pinned deterministic release dependencies
└── AGENTS.md              # AI agent rules and architectural invariants
```

---

## 📦 Supported Archive Formats

- **`.cbz` (Comic Book ZIP)**: Supported natively. Updated in-place using temporary files with CRC and SHA256 verification.
- **`.cbr` (Comic Book RAR)**: Requires `unrar`, `rar`, or `7z` available on the system `PATH`. Converted to `.cbz` before metadata embedding; the original `.cbr` is deleted only after post-embed archive verification passes.

---

## ⚠️ Known Limitations & Edge Cases

- **Comic Vine Anti-Bot / Rate Limiting**: Unauthenticated Comic Vine requests may encounter Cloudflare verification or rate limits. Configuring a valid `COMICVINE_API_KEY` is strongly recommended for large libraries.
- **Series Disambiguation**: Series sharing identical names (e.g. *Batman (1940)* vs *Batman (2016)*) rely on year metadata. If the filename omits the publication year, the pipeline flags the item for manual review.
- **Variant Numbering**: Variants such as `#1A`, `#0.5`, `Annual`, and `Special` are parsed into canonical sort orders, but require provider issue records matching those designations.
- **Network Outages**: If Kapowarr or Comic Vine is offline, the pipeline safely falls back to cached metadata or secondary providers without corrupting local files.

---

## 🧪 Running the Test Suite

The repository includes a comprehensive 306+ test regression suite that runs completely offline with mocked provider fixtures:

```bash
# Run full test discovery
python -m unittest discover tests -v

# Run specific integration test
python -m unittest tests.test_cli_dry_run_integration -v
```

---

## 📄 License

MIT License. Free to use, modify, and distribute.
