# 📚 ComicInfo Generator & Tagger

A powerful, modern web application and CLI tool to automatically scrape rich comic book metadata from Comic Vine, convert `.cbr` archives to `.cbz`, merge multi-issue Trade Paperbacks (TPBs), and embed standard `ComicInfo.xml` files into your comic archives.

---

## 🌟 Key Features

- **📄 Single Issue & TPB Mode**: Tag single issues or merge multiple Comic Vine issue URLs into a single Trade Paperback / Collected Edition archive (`Number: 1-6`, `Count: 6`, merged creators, characters, teams, story arcs, and summaries).
- **📁 Batch Series Folder Mode**: Provide a series folder directory and a Comic Vine Volume URL (`/4050-XXXXX/`). Automatically scrapes all volume pages (including multi-page series) and matches local issue files (`#1`, `#2`, `#57`, `#100`).
- **🛡️ Cloudflare Protection Bypass**: Built-in scraper fallback pipeline utilizing `curl_cffi` and `cloudscraper` to reliably bypass Cloudflare anti-bot checks on Comic Vine.
- **📦 Automatic CBR to CBZ Converter**: Includes official RARLAB `unrar` binary with `-kb` (*Keep Broken/Repaired*) recovery. Automatically converts `.cbr` files to `.cbz` and safely removes original `.cbr` files upon 100% verified conversion.
- **🏷️ Rich ComicInfo.xml Schema**: Tags `<Title>`, `<Series>`, `<Number>`, `<Volume>`, `<Count>`, `<Summary>`, `<Year>`, `<Month>`, `<Day>`, `<Publisher>`, `<Web>`, `<Writer>`, `<Penciller>`, `<Inker>`, `<Colorist>`, `<Letterer>`, `<CoverArtist>`, `<Characters>`, `<Teams>`, and `<StoryArc>`. Fully compatible with Kavita, Komga, YACReader, and ComicRack.
- **🔍 Per-File Live Inspection & Manual Overrides**: Inspect extracted metadata per-file with collapsible detail drawers, or manually link any unmatched file using interactive dropdown menus.
- **📊 Real-Time Terminal Log & Progress Bar**: Visual progress tracking and step-by-step execution logs during batch tagging.

---

## 🚀 Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/jakej985-rgb/comicinfo-generator.git
cd comicinfo-generator

# Create a virtual environment and install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Launch Web UI

```bash
python main.py --web
```

Then open your browser to **`http://localhost:5000`** (or `http://localhost:5001`).

---

## 💻 CLI Usage

### Tag a single comic archive

```bash
python main.py "path/to/comic.cbz" "https://comicvine.gamespot.com/batman-1-the-dark-knight/4000-12345/"
```

### Batch tag an entire series volume page

```bash
python main.py "https://comicvine.gamespot.com/angelus/4050-69279/"
```

---

## 📁 Repository Structure

```
comicinfo-generator/
├── app.py                 # HTTP REST Server & API Endpoints
├── main.py                # CLI entry point
├── models/
│   └── comic.py           # Comic Data Model & Multi-Issue Merger
├── providers/
│   └── comicvine.py       # Cloudflare-Bypassing Web Scraper
├── converters/
│   └── cbr_to_cbz.py      # RARLAB RAR5 CBR -> CBZ Converter
├── writers/
│   ├── archive.py         # Zip archive writer
│   └── comicinfo.py       # ComicInfo.xml generator
├── static/                # Web UI (HTML, CSS Glassmorphism, JS)
├── bin/
│   └── unrar              # Official RARLAB unrar binary
└── requirements.txt
```

---

## 📄 License

MIT License. Free to use, modify, and distribute for personal and open-source projects!
