# 📚 ComicInfo Generator & Tagger

A powerful, modern web application and CLI tool to automatically scrape rich comic book metadata from **Comic Vine** and **Grand Comics Database (comics.org / GCP)**, convert `.cbr` (RAR/RAR5) archives to `.cbz` (ZIP), merge multi-issue Trade Paperbacks (TPBs), and embed standardized `ComicInfo.xml` files into your comic archives.

---

## 🤖 AI Disclosure

This project was created and developed with significant assistance from autonomous AI pair programming agents (**Google DeepMind Antigravity** / **Gemini**). AI was utilized for system architecture design, web scraping & Cloudflare bypass implementation, multi-provider metadata parsing, glassmorphic Web UI creation, and Docker containerization.

---

## 🌟 Key Features

- **🌐 Dual Database Scraping**:
  - **Comic Vine**: Scrapes issues, volumes/series, creator credits, character lists, teams, story arcs, and high-res cover artwork links.
  - **Grand Comics Database (GCP / comics.org)**: Supports GCP issue and series URLs (`/issue/XXXXX/`, `/series/XXXXX/`), direct page scraping, Wayback Machine cache fallbacks, and raw text layout parsing.
- **📄 Single Issue & TPB Mode**: Tag single issues or merge multiple comic issue URLs into a single Trade Paperback / Collected Edition archive (`Number: 1-6`, `Count: 6`, merged creators, characters, teams, story arcs, and combined plot summaries).
- **📁 Batch Series Folder Mode**: Provide a local series directory and a Volume / Series URL. Automatically scrapes all series issues (including multi-page volumes) and matches local files (`#1`, `#2`, `#57`, `#100`).
- **🛡️ Cloudflare Protection Bypass**: Built-in scraper pipeline utilizing `curl_cffi` (browser impersonation) and `cloudscraper` alongside HTTPS Wayback Machine fallbacks to reliably bypass Cloudflare anti-bot verification.
- **📦 Automatic CBR to CBZ Converter**: Integrates official `unrar` / `unar` extraction with `-kb` (*Keep Broken/Repaired*) recovery. Automatically converts `.cbr` files to `.cbz` and safely deletes original `.cbr` files only after 100% verified conversion.
- **🏷️ Rich ComicInfo.xml Schema**: Embeds standard tags (`<Title>`, `<Series>`, `<Number>`, `<Volume>`, `<Count>`, `<Summary>`, `<Year>`, `<Month>`, `<Day>`, `<Publisher>`, `<Web>`, `<Writer>`, `<Penciller>`, `<Inker>`, `<Colorist>`, `<Letterer>`, `<CoverArtist>`, `<Characters>`, `<Teams>`, and `<StoryArc>`). Fully compatible with Kavita, Komga, YACReader, and ComicRack.
- **🔍 Live Inspection & Manual Overrides**: Preview extracted metadata per-file with collapsible drawers, inspect character & creator lists, and manually map unmatched files using interactive dropdown menus in the Web UI.

---

## 🐳 Docker Setup & Usage

### Option 1: Docker Compose (Recommended)

Run the Web UI in a detached Docker container:

```bash
docker compose up -d
```

Open **`http://localhost:5005`** in your browser.

To stop the container:
```bash
docker compose down
```

### Option 2: Docker CLI

1. **Build the image**:
   ```bash
   docker build -t comicinfo-generator:v0.1 .
   ```

2. **Run the container (mounting your comic directory)**:
   ```bash
   docker run -d -p 5005:5005 -v /path/to/your/comics:/comics --name comicinfo-generator ghcr.io/jakej985-rgb/comicinfo-generator:v0.1
   ```

3. Open **`http://localhost:5005`**.

---

## 🚀 Quick Start (Local Setup)

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

Open **`http://localhost:5005`** in your browser.

---

## 💻 CLI Usage

### Launch Web UI on a custom port

```bash
python main.py --web 5005
```

### Tag a single comic archive

```bash
python main.py "path/to/comic.cbz" "https://comicvine.gamespot.com/batman-1-the-dark-knight/4000-12345/"
```

### Convert CBR to CBZ archive

```bash
python main.py convert "path/to/comic.cbr"
```

### Generate standalone ComicInfo.xml file

```bash
python main.py "https://comicvine.gamespot.com/angelus-1-part-1/4000-12345/"
```

---

## 📁 Repository Structure

```
comicinfo-generator/
├── app.py                 # HTTP REST Server & API Endpoints
├── main.py                # CLI entry point & launcher
├── Dockerfile             # Container build definition
├── docker-compose.yml     # Docker Compose specification
├── models/
│   └── comic.py           # Comic Data Model & Multi-Issue Merger
├── providers/
│   ├── comicvine.py       # Comic Vine Cloudflare-Bypassing Scraper
│   └── gcp.py             # Grand Comics Database (GCP / comics.org) Scraper
├── converters/
│   └── cbr_to_cbz.py      # RAR5 CBR -> CBZ Converter
├── writers/
│   ├── archive.py         # Zip archive writer & metadata embedder
│   └── comicinfo.py       # ComicInfo.xml generator
├── static/                # Glassmorphic Web UI (HTML, CSS, JS)
├── bin/
│   └── unrar              # Bundled RARLAB unrar binary
└── requirements.txt       # Python dependencies
```

---

## 📄 License

MIT License. Free to use, modify, and distribute for personal and open-source projects!
