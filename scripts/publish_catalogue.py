"""Export the static registry catalogue for GitHub Pages."""
import argparse
import json
from pathlib import Path
import shutil

from registry import Registry
from registry import within

ROOT = Path(__file__).resolve().parents[1]


def registry_url(repository):
    owner, repo = repository.split('/')
    base = '' if repo.lower() == f'{owner.lower()}.github.io' else f'/{repo}'
    return f'https://{owner}.github.io{base}/registry/index.json'


def package_base_url(repository):
    return registry_url(repository).removesuffix('index.json') + 'packages'


def publish_catalogue(root, destination):
    registry = Registry(root)
    destination.mkdir(parents=True, exist_ok=True)
    extensions = []
    for extension in registry.names():
        metadata = registry.metadata(extension)
        output = destination / 'extensions' / extension
        output.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            within(registry.directory, f'{extension}/metadata.json'),
            output / 'metadata.json')
        for version in metadata['versions']:
            registry.manifest(extension, version)
            registry.external_packages(extension, version)
            source = registry.source(extension, version)
            version_output = output / version
            version_output.mkdir(exist_ok=True)
            for name in ('manifest.json', 'packages.yaml', 'packages.json'):
                path = within(source, name)
                if path.is_file():
                    shutil.copyfile(path, version_output / name)
        extensions.append(metadata)
    data = {
        'schemaVersion':
            1,
        'index':
            'index.json' if (destination / 'index.json').is_file() else None,
        'extensions':
            extensions,
    }
    (destination / 'registry-data.json').write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index-url', metavar='OWNER/REPO')
    args = parser.parse_args()
    if args.index_url:
        print(registry_url(args.index_url))
    else:
        publish_catalogue(ROOT, ROOT / 'website/public/registry')


if __name__ == '__main__':
    main()
