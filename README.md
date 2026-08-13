# 📚 ComicInfo Generator & Tagger

A powerful, modern web application to automatically scrape rich comic book metadata from Comic Vine, convert `.cbr` archives to `.cbz`, merge multi-issue Trade Paperbacks (TPBs), and embed standard `ComicInfo.xml` files into your comic archives.

---

## 🌟 Key Features

- **📄 Single Issue & TPB Mode**: Tag single issues or merge multiple Comic Vine issue URLs into a single Trade Paperback / Collected Edition archive (`Number: 1-6`, `Count: 6`, merged creators, characters, teams, story arcs, and summaries).
- **📁 Batch Series Folder Mode**: Provide a series folder directory and a Comic Vine Volume URL (`/4050-XXXXX/`). Automatically scrapes all volume pages (including multi-page series) and matches local issue files (`#1`, `#2`, `#57`, `#100`).
- **📚 Story Arc & Crossover Tracker**: Track, search, and batch-tag full multi-series crossovers (e.g. *Marvel Zombies*, *Civil War*, *House of M*) across your library or monitored Kapowarr volumes.
- **⚡ Kapowarr Integration**: Full two-way sync with Kapowarr library volumes.
- **🛡️ Cloudflare Protection Bypass**: Built-in scraper fallback pipeline utilizing `curl_cffi` and `cloudscraper` to reliably bypass Cloudflare anti-bot checks on Comic Vine.
- **📦 Automatic CBR to CBZ Converter**: Includes official RARLAB `unrar` binary with `-kb` (*Keep Broken/Repaired*) recovery. Automatically converts `.cbr` files to `.cbz` and safely removes original `.cbr` files upon 100% verified conversion.
- **🏷️ Rich ComicInfo.xml Schema**: Tags `<Title>`, `<Series>`, `<Number>`, `<Volume>`, `<Count>`, `<Summary>`, `<Year>`, `<Month>`, `<Day>`, `<Publisher>`, `<Web>`, `<Writer>`, `<Penciller>`, `<Inker>`, `<Colorist>`, `<Letterer>`, `<CoverArtist>`, `<Characters>`, `<Teams>`, `<StoryArc>`, and `<StoryArcNumber>`. Fully compatible with Kavita, Komga, YACReader, and ComicRack.

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

### 2. Launch Web App Server

```bash
python main.py
```

Then open your browser to **`http://localhost:5005`**.

---

## 📁 Repository Structure

```
comicinfo-generator/
├── app.py                 # HTTP REST Server & Web API Endpoints
├── main.py                # Web App Application Entry Point
├── models/
│   └── comic.py           # Comic Data Model & Multi-Issue Merger
├── providers/
│   ├── comicvine.py       # Cloudflare-Bypassing Web Scraper
│   ├── story_arc.py       # Story Arc Scraper & Cross-Referencer
│   └── kapowarr.py        # Kapowarr Library Integration
├── converters/
│   └── cbr_to_cbz.py      # RARLAB RAR5 CBR -> CBZ Converter
├── writers/
│   ├── archive.py         # Zip archive writer
│   └── comicinfo.py       # ComicInfo.xml generator
├── static/                # Web UI (HTML, Glassmorphism CSS, JS)
├── bin/
│   └── unrar              # Official RARLAB unrar binary
└── requirements.txt
```

---

## 📄 License

MIT License. Free to use, modify, and distribute for personal and open-source projects!
