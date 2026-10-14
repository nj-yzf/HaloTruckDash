"""Generate latest.json for an HTTPS folder or GitHub Release assets."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from halo_dashboard.updates import FORMAT, file_digest, parse_manifest
from halo_dashboard.version import VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--download-url', help='HTTPS URL; defaults to a ZIP alongside latest.json')
    parser.add_argument('--notes', default='')
    args = parser.parse_args()
    document = {'format': FORMAT, 'schema': 1, 'version': VERSION,
                'notes': args.notes,
                'windows_x64': {'url': args.download_url or args.archive.name,
                                'size': args.archive.stat().st_size,
                                'sha256': file_digest(args.archive)}}
    # Only validates the document; this reserved URL is never contacted.
    parse_manifest(document, 'https://updates.invalid/latest.json')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Update manifest: {args.output}')


if __name__ == '__main__':
    main()
