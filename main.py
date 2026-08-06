import sys
import os
from config import load_config
from app import run_server
from cli import run_cli

def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("--web", "-w"):
        port = 5005
        for arg in sys.argv[1:]:
            if arg.isdigit():
                port = int(arg)
        run_server(port)
        return

    # Route all CLI commands through cli.py handler
    run_cli()

if __name__ == "__main__":
    main()
