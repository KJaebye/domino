#!/usr/bin/env python3
"""Read-only checks on public source candidates; never print matched secret values."""
import ast
import json
from pathlib import Path
import re
import subprocess
import unicodedata
from urllib.parse import unquote, urlsplit

ROOT=Path(__file__).resolve().parents[1]
REQUIRED=['README.md','CHANGELOG.md','NOTICE','CONTRIBUTING.md','SECURITY.md','pyproject.toml',
          'docs/USAGE.md','docs/PLATFORMS.md','.github/workflows/verify.yml']
SECRET_RULES={
    'private-key':rb'(?m)^-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
    'github-token':rb'\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b',
    'aws-access-key':rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
}


def candidates(root):
    try:
        result=subprocess.run(['git','ls-files','-z','--cached','--others','--exclude-standard'],
                              cwd=root,check=True,capture_output=True)
        return sorted({Path(name.decode()) for name in result.stdout.split(b'\0') if name and (root/name.decode()).exists()})
    except (OSError,subprocess.CalledProcessError):
        excluded={'.git','.venv','dist','build','__pycache__','.test-resources'}
        return sorted(p.relative_to(root) for p in root.rglob('*') if p.is_file() and not excluded.intersection(p.relative_to(root).parts)
                      and not any(part.endswith('.egg-info') for part in p.parts))


def headings(text):
    result=set();fenced=False
    for line in text.splitlines():
        if line.lstrip().startswith('```'):fenced=not fenced
        if fenced:continue
        match=re.match(r'^#{1,6} (.+)$',line)
        if match:
            value=re.sub(r'<[^>]+>','',match[1]).strip().lower().replace(' ','-')
            result.add(''.join(c for c in value if c in '-_' or not unicodedata.category(c).startswith(('P','S'))))
    return result


def inspect(root):
    errors=[];warnings=[];files=candidates(root);links=0;python_files=0
    for name in REQUIRED:
        if not (root/name).is_file():errors.append({'path':name,'rule':'missing-public-file'})
    if not (root/'LICENSE').is_file():warnings.append('Project license is not selected; choose it before open-source distribution.')
    for relative in files:
        path=root/relative;name=relative.as_posix()
        if path.is_symlink():errors.append({'path':name,'rule':'unexpected-symlink'});continue
        if relative.parts[0] in ['.venv','dist','build','.test-resources'] or relative.suffix in ['.whl','.gz','.deb','.changes','.buildinfo','.pem','.key','.db'] or (relative.name.startswith('.env') and relative.name!='.env.example'):
            errors.append({'path':name,'rule':'private-or-generated-file'});continue
        if path.suffix in ['.gif','.png','.webp']:continue
        data=path.read_bytes()
        for rule,pattern in SECRET_RULES.items():
            for match in re.finditer(pattern,data):errors.append({'path':name,'line':data[:match.start()].count(b'\n')+1,'rule':rule})
        if path.suffix=='.py':
            python_files+=1
            try:ast.parse(data,filename=name,feature_version=(3,9))
            except SyntaxError as error:errors.append({'path':name,'line':error.lineno,'rule':'python39-syntax'})
        if path.suffix=='.md':
            text=re.sub(r'```.*?```','',data.decode(),flags=re.S)
            for target in re.findall(r'\]\(([^)\s]+)\)|(?:src|href)="([^"]+)"',text):
                value=next(v for v in target if v);url=urlsplit(value)
                if url.scheme or url.netloc:continue
                location=path.parent/unquote(url.path) if url.path else path
                if not location.exists():errors.append({'path':name,'rule':'broken-local-link','target':value})
                elif url.fragment and location.suffix=='.md' and unquote(url.fragment) not in headings(location.read_text()):
                    errors.append({'path':name,'rule':'broken-local-anchor','target':value})
                links+=1
    tree=ast.parse((root/'domino_cli.py').read_text())
    declarations={node.targets[0].id:ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign)
                  and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ['VERSION','CLI_MODULES']}
    for name in declarations['CLI_MODULES']:
        if Path(name) not in files:errors.append({'path':name,'rule':'module-not-in-public-candidates'})
    match=re.search(r'(?m)^version\s*=\s*"([^"]+)"',(root/'pyproject.toml').read_text())
    if not match or match[1]!=declarations['VERSION']:errors.append({'rule':'version-mismatch'})
    for workflow in (root/'.github/workflows').glob('*.yml'):
        for line in workflow.read_text().splitlines():
            if 'uses:' in line and 'uses: ./' not in line and not re.search(r'uses:\s+[^\s@]+@[a-f0-9]{40}(?:\s|$)',line):
                errors.append({'path':workflow.relative_to(root).as_posix(),'rule':'action-not-pinned'})
    return {'version':declarations['VERSION'],'ok':not errors,'public_candidate_files':len(files),
            'python39_syntax_files':python_files,'local_document_links':links,'license_selected':(root/'LICENSE').is_file(),
            'secret_values_printed':False,'errors':errors,'warnings':warnings}


def main():
    report=inspect(ROOT);output=ROOT/'dist/repository-verification.json';output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__=='__main__':raise SystemExit(main())
