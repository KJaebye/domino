#!/usr/bin/env python3
"""Build versioned local artifacts; never publish, install, or read user config."""
import argparse
import ast
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import domino_cli as cli

DISTRIBUTION = 'domino-proxy'
WHEEL_NAME = DISTRIBUTION.replace('-', '_')

def wheel_name(version, distribution=DISTRIBUTION):
    return distribution.replace('-', '_') + f'-{version}-py3-none-any.whl'


DOCUMENT_FILES = ('README.md','README.pypi.md','CHANGELOG.md','NOTICE','SECURITY.md','CONTRIBUTING.md') + tuple(
    sorted(path.relative_to(ROOT).as_posix() for pattern in ['LICENSE','docs/*.md','assets/*','licenses/*']
           for path in ROOT.glob(pattern) if path.is_file()))
SOURCE_FILES = ('pyproject.toml',) + cli.CLI_MODULES + DOCUMENT_FILES


def source_version(inputs):
    """Check both literal declarations without importing the staged CLI (Python 3.9+)."""
    tree = ast.parse(inputs['domino_cli.py'].decode('utf-8'))
    versions = [ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == 'VERSION'
                        for target in node.targets)]
    # Only read the simple literal under [project], not other TOML version keys.
    sections = re.split(r'(?m)^\[project\][ \t]*(?:#.*)?$', inputs['pyproject.toml'].decode('utf-8'))
    project = re.split(r'(?m)^\s*\[', sections[1], maxsplit=1)[0] if len(sections) == 2 else ''
    declared = re.findall(r'(?m)^version[ \t]*=[ \t]*(.*)$', project)
    package = re.fullmatch(r'''(["'])(0\.\d+\.\d+)\1[ \t]*(?:#.*)?''', declared[0]) if len(declared) == 1 else None
    if (len(versions) != 1 or not isinstance(versions[0], str)
            or not re.fullmatch(r'0\.\d+\.\d+', versions[0]) or package is None
            or versions[0] != package[2] or versions[0] != cli.VERSION):
        raise ValueError('CLI VERSION and [project] version must match and use 0.x.y')
    return versions[0]


def hashes(inputs):
    return {name: hashlib.sha256(value).hexdigest() for name, value in inputs.items()}


def formula_text(archive, version, digest, base):
    return '''class Domino < Formula
  desc "Command-line proxy management and independent deployment"
  homepage "https://github.com/KJaebye/domino"
  url "BASE/ARCHIVE"
  version "VERSION"
  sha256 "DIGEST"
  depends_on "python@3.13"

  def install
    libexec.install "cli"
    { "domino" => "package_cli", "domino-install" => "package_install" }.each do |name, entry|
      (bin/name).write <<~EOS
        #!#{Formula["python@3.13"].opt_bin}/python3.13
        import sys
        sys.path[:0] = ["#{libexec}/cli", "#{libexec}/cli/_vendor"]
        from domino_install import #{entry}
        raise SystemExit(#{entry}())
      EOS
      (bin/name).chmod 0755
    end
    doc.install "README.md", "CHANGELOG.md", "NOTICE", "docs", "licenses"
    doc.install "LICENSE" if File.exist?("LICENSE")
  end

  def caveats
    <<~EOS
      CLI installed. To initialize your local proxy service, run as your normal user:
        domino-install
      Package upgrades do not change running services, configuration, or system proxy.
    EOS
  end

  test do
    system bin/"domino", "--version"
  end
end
'''.replace('BASE', base).replace('ARCHIVE', archive).replace('VERSION', version).replace('DIGEST', digest)


def build(source, artifacts, inputs, version, base_url):
    from packaging.specifiers import SpecifierSet
    for dependency in ['prompt-toolkit','wcwidth','PyYAML']:
        requirement=importlib.metadata.metadata(dependency).get('Requires-Python','')
        if requirement and '3.9' not in SpecifierSet(requirement):
            raise RuntimeError(f'{dependency} does not support Python 3.9; install .[dev] before building the runtime')
    for name, content in inputs.items():
        (source / name).parent.mkdir(parents=True,exist_ok=True)
        (source / name).write_bytes(content)
    subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-build-isolation', '--no-deps',
                    '--no-index', str(source), '--wheel-dir', str(artifacts), '--quiet'], check=True)
    wheel = artifacts / wheel_name(version)
    if not wheel.is_file() or set(artifacts.iterdir()) != {wheel}:
        raise RuntimeError('Wheel build did not produce exactly the expected versioned wheel')
    package = source.parent / f'domino-{version}'
    package.mkdir()
    cli.copy_cli(package)
    # copy_cli supplies dependencies/licenses. Both artifacts use the frozen project inputs.
    for name in cli.CLI_MODULES:
        (package / 'cli' / name).write_bytes(inputs[name])
    if not all((package / 'cli/_vendor' / name).is_dir() for name in ['yaml', 'prompt_toolkit', 'wcwidth']):
        raise RuntimeError('Install project dependencies before building the runtime archive')
    for name in DOCUMENT_FILES:
        (package / name).parent.mkdir(parents=True,exist_ok=True)
        (package / name).write_bytes(inputs[name])
    for name, module in [('domino', 'domino_cli'), ('domino-install', 'domino_install')]:
        binary = package / 'bin' / name
        binary.parent.mkdir(exist_ok=True)
        binary.write_text('#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\n'
                          'root=Path(__file__).resolve().parents[1]/"cli"\n'
                          'sys.path[:0]=[str(root),str(root/"_vendor")]\n'
                          f'from {module} import main\nraise SystemExit(main())\n')
        binary.chmod(0o755)
    archive = artifacts / f'domino-runtime-{version}.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        bundle.add(package, arcname=package.name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    base = base_url.rstrip('/') if base_url else 'https://REPLACE-WITH-PUBLIC-ARTIFACT-HOST'
    formula = artifacts / ('domino.rb' if base_url else 'domino.rb.in')
    formula.write_text(formula_text(archive.name, version, digest, base))
    return [wheel, archive, formula]


def publish(artifacts, output):
    """Reserve exclusively; release.json is the completion marker, always moved last."""
    output.mkdir()  # No exist_ok: refuse even empty directories and dangling symlinks.
    try:
        for path in sorted(artifacts.iterdir(), key=lambda p: p.name == 'release.json'):
            path.rename(output / path.name)
    except BaseException:
        shutil.rmtree(output)
        raise


def previous_release(output):
    """Read and validate the old flat release before replacing its mutable metadata."""
    if output.is_symlink() or (output.exists() and not output.is_dir()):
        raise ValueError('Release output must be a real directory')
    manifest = output / 'release.json'
    if not manifest.exists() and not manifest.is_symlink():
        if any((output / name).exists() or (output / name).is_symlink()
               for name in ('SHA256SUMS', 'domino.rb', 'domino.rb.in')):
            raise ValueError('Release metadata exists without release.json; inspect it before building')
        return {}
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError('release.json must be a regular file')
    data = json.loads(manifest.read_text())
    version = data.get('version', '')
    if not isinstance(version, str) or not re.fullmatch(r'0\.\d+(?:\.\d+)?', version):
        raise ValueError('Invalid previous release version')
    expected = {wheel_name(version, data.get('distribution', 'domino')), f'domino-runtime-{version}.tar.gz'}
    entries = data.get('files', [])
    names = [item['name'] for item in entries]
    if (len(names) != 3 or len(set(names)) != 3
            or set(names) not in (expected | {'domino.rb.in'}, expected | {'domino.rb'})):
        raise ValueError('Unexpected files in previous release manifest')
    snapshot = {'release.json': manifest.read_bytes()}
    for name in names + ['SHA256SUMS']:
        path = output / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Previous release file is missing or not regular: ' + name)
        snapshot[name] = path.read_bytes()
    for item in entries:
        content = snapshot[item['name']]
        if len(content) != item['bytes'] or hashlib.sha256(content).hexdigest() != item['sha256']:
            raise ValueError('Previous release checksum mismatch: ' + item['name'])
    lines = [line.split('  ') for line in snapshot['SHA256SUMS'].decode().splitlines()]
    sums = {name: digest for digest, name in lines}
    if (len(sums) != len(lines) or set(sums) not in (set(names), set(names) | {'release.json'})
            or sums != hashes({name: snapshot[name] for name in sums})):
        raise ValueError('Previous SHA256SUMS does not match its release')
    return snapshot


def flat_preflight(output, version):
    snapshot = previous_release(output)
    for path in (output / wheel_name(version),
                 output / f'domino-runtime-{version}.tar.gz',
                 output.parent / wheel_name(version)):
        if path.exists() or path.is_symlink():
            raise FileExistsError('Version already built; do not overwrite: ' + str(path))
    if snapshot:
        previous = json.loads(snapshot['release.json'])['version']
        if previous == version:
            raise ValueError('Version already built; increment the version for changed code')
        history = output / 'history'
        target = history / previous
        if history.is_symlink() or (history.exists() and not history.is_dir()):
            raise ValueError('Release history must be a real directory')
        if target.exists() or target.is_symlink():
            raise FileExistsError('Previous release archive already exists: ' + str(target))
    return snapshot


@contextmanager
def flat_release_lock(output, version):
    """Serialize default builds; never remove a lock owned by another invocation."""
    lock = output.parent / '.domino-release.lock'
    lock.mkdir()
    try:
        yield flat_preflight(output, version)
    finally:
        lock.rmdir()


def publish_flat(artifacts, output, version, previous):
    """Keep the historical flat layout, archive old metadata, and commit the manifest last."""
    if flat_preflight(output, version) != previous:
        raise RuntimeError('Previous release changed during build; no release delivered')
    new_directory = not output.exists()
    output.mkdir(exist_ok=True)
    history_target = None
    created, replaced = [], []
    try:
        if previous:
            old = artifacts.parent / 'previous'
            old.mkdir()
            for name, content in previous.items():
                (old / name).write_bytes(content)
            target = output / 'history' / json.loads(previous['release.json'])['version']
            target.parent.mkdir(exist_ok=True)
            publish(old, target)
            history_target = target
        # Versioned packages are exclusive, including the traditional wheel copy in dist/.
        wheel = artifacts / wheel_name(version)
        for source, target in [(wheel, output.parent / wheel.name),
                               (wheel, output / wheel.name),
                               (artifacts / f'domino-runtime-{version}.tar.gz',
                                output / f'domino-runtime-{version}.tar.gz')]:
            with target.open('xb') as destination:
                created.append(target)
                with source.open('rb') as stream:
                    shutil.copyfileobj(stream, destination)
        # Keep only the current formula type at the flat release root; the old one is archived.
        for name in ('domino.rb', 'domino.rb.in'):
            if name in previous and not (artifacts / name).exists():
                target = output / name
                replaced.append(target)
                target.unlink()
        for path in sorted(artifacts.iterdir(), key=lambda p: p.name == 'release.json'):
            if path.name.endswith(('.whl', '.tar.gz')):
                continue
            target = output / path.name
            if (target.exists() or target.is_symlink()) and path.name not in previous:
                raise FileExistsError('Untracked release metadata will not be overwritten: ' + str(target))
            replaced.append(target)
            path.replace(target)
    except BaseException as error:
        failures = []
        for target in reversed(replaced):
            try:
                if target.name in previous:
                    restore = artifacts / ('restore-' + target.name)
                    restore.write_bytes(previous[target.name])
                    restore.replace(target)
                else:
                    target.unlink(missing_ok=True)
            except OSError as recovery:
                failures.append(str(recovery))
        for target in reversed(created):
            try:
                target.unlink()
            except OSError as recovery:
                failures.append(str(recovery))
        if history_target is not None and history_target.exists() and not failures:
            shutil.rmtree(history_target)
        if new_directory and not any(output.iterdir()):
            output.rmdir()
        if failures:
            raise RuntimeError('Release failed; metadata recovery incomplete: ' + '; '.join(failures)) from error
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, help='New isolated output directory (default: flat dist/release)')
    parser.add_argument('--base-url', help='Public HTTPS artifact directory; omit for an unpublished formula template')
    args = parser.parse_args()
    if args.base_url:
        parsed = urlsplit(args.base_url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            parser.error('--base-url must be a public HTTPS directory')
    try:
        inputs = {name: (ROOT / name).read_bytes() for name in SOURCE_FILES}
        version = source_version(inputs)
    except (OSError, ValueError, SyntaxError, TypeError) as error:
        parser.error('Version/source preflight failed: ' + str(error))
    output = Path(os.path.abspath(args.output or ROOT / 'dist/release'))
    if args.output and (output.exists() or output.is_symlink()):
        parser.error('Output already exists; choose a new directory. Existing builds are never overwritten.')
    source_hashes = hashes(inputs)
    builder = Path(__file__).read_bytes()
    output.parent.mkdir(parents=True, exist_ok=True)
    with (nullcontext(None) if args.output else flat_release_lock(output, version)) as previous:
        with tempfile.TemporaryDirectory(prefix='.domino-build-', dir=output.parent) as directory:
            work = Path(directory)
            source, artifacts = work / 'source', work / 'artifacts'
            source.mkdir()
            artifacts.mkdir()
            paths = build(source, artifacts, inputs, version, args.base_url)
            if (hashes({name: (ROOT / name).read_bytes() for name in SOURCE_FILES}) != source_hashes
                    or Path(__file__).read_bytes() != builder):
                raise RuntimeError('Sources changed during the build; no release delivered. Rebuild from a stable tree.')
            entries = [{'name': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                        'bytes': path.stat().st_size} for path in sorted(paths)]
            manifest = {'schema_version': 1, 'distribution': DISTRIBUTION, 'version': version, 'published': False,
                        'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                        'python': sys.version.split()[0], 'source_files': source_hashes,
                        'build_script_sha256': hashlib.sha256(builder).hexdigest(), 'files': entries}
            release = artifacts / 'release.json'
            release.write_text(json.dumps(manifest, indent=2) + '\n')
            sums = ''.join(item['sha256'] + '  ' + item['name'] + '\n' for item in entries)
            sums += hashlib.sha256(release.read_bytes()).hexdigest() + '  release.json\n'
            (artifacts / 'SHA256SUMS').write_text(sums)
            if args.output:
                publish(artifacts, output)
            else:
                publish_flat(artifacts, output, version, previous)
    print(json.dumps({'output': str(output), 'version': version, 'published': False,
                      'files': [item['name'] for item in entries]}))


if __name__ == '__main__':
    main()
