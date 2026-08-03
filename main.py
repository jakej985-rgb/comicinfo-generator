import sys
import os
from providers.comicvine import scrape_issue
from writers.comicinfo import write_xml
from writers.archive import embed_comicinfo_in_cbz
from converters.cbr_to_cbz import convert_cbr_to_cbz
from app import run_server

def print_usage():
    print("Usage:")
    print("  Launch Web UI:                 python main.py --web")
    print("  Embed into CBZ/CBR archive:   python main.py <comic_file.cbz|cbr> <comicvine_issue_url>")
    print("  Convert CBR to CBZ only:       python main.py convert <comic_file.cbr>")
    print("  Generate standalone XML:       python main.py <comicvine_issue_url>")

def main():
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print_usage()
        sys.exit(1)

    args = sys.argv[1:]

    # Check for --web flag
    if "--web" in args or "-w" in args:
        port = 5000
        for arg in args:
            if arg.isdigit():
                port = int(arg)
        run_server(port)
        return

    # Check for convert command
    if args[0] == "convert" and len(args) == 2:
        cbr_file = args[1]
        try:
            print(f"Converting '{cbr_file}' to CBZ format...")
            cbz_path = convert_cbr_to_cbz(cbr_file)
            print(f"Successfully converted to '{cbz_path}'.")
        except Exception as e:
            print(f"Error converting CBR to CBZ: {e}")
            sys.exit(1)
        return

    url = None
    cbz_file = None

    for arg in args:
        if arg.startswith("http://") or arg.startswith("https://"):
            url = arg
        elif arg.lower().endswith(".cbz") or arg.lower().endswith(".cbr") or os.path.exists(arg):
            cbz_file = arg
        else:
            if url is None:
                url = arg

    if not url:
        print("Error: No Comic Vine URL provided.")
        print_usage()
        sys.exit(1)

    print(f"Fetching metadata from: {url}")
    try:
        comic = scrape_issue(url)
    except Exception as e:
        print(f"Error fetching issue metadata: {e}")
        sys.exit(1)

    print(f"Scraped Comic Metadata:")
    print(f"  Series: {comic.series}")
    print(f"  Number: #{comic.number}")
    print(f"  Title:  {comic.title}")
    if comic.publisher:
        print(f"  Publisher: {comic.publisher}")
    if comic.year:
        print(f"  Date: {comic.year}-{comic.month:02d}-{comic.day:02d}")

    if cbz_file:
        try:
            target_file = cbz_file
            if cbz_file.lower().endswith(".cbr"):
                print(f"Converting CBR file '{cbz_file}' to CBZ format first...")
                target_file = convert_cbr_to_cbz(cbz_file)

            print(f"Embedding ComicInfo.xml into archive: {target_file}...")
            embed_comicinfo_in_cbz(target_file, comic)
            print(f"Successfully embedded ComicInfo.xml into '{target_file}'.")
        except Exception as e:
            print(f"Error embedding ComicInfo.xml into archive: {e}")
            sys.exit(1)
    else:
        out_path = "ComicInfo.xml"
        try:
            write_xml(comic, out_path)
            print(f"Successfully created '{out_path}'.")
        except Exception as e:
            print(f"Error creating XML file: {e}")
            sys.exit(1)

if __name__ == "__main__":
    main()
