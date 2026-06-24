import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hail_engine import resolve_latest_mesh_url_from_sources

if __name__ == "__main__":
    url = resolve_latest_mesh_url_from_sources()
    print(url)
