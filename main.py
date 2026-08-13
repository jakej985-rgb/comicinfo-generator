import sys
import os
from config import load_config
from app import run_server

def main():
    port = 5005
    for arg in sys.argv[1:]:
        if arg.isdigit():
            port = int(arg)
    run_server(port)

if __name__ == "__main__":
    main()
