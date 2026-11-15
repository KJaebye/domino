#!/usr/bin/env python3
"""Stage public resource files from a verified upstream release and local Geo data."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
from urllib.parse import urlsplit


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',required=True)
    parser.add_argument('--release-json',type=Path,required=True)
    parser.add_argument('--archive',type=Path,action='append',required=True)
    parser.add_argument('--geo-dir',type=Path)
    parser.add_argument('--output',type=Path,default=Path('dist/resources'))
    args=parser.parse_args()
    url=urlsplit(args.base_url)
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        parser.error('base URL must be a public HTTPS directory')
    base=args.base_url.rstrip('/')+'/'
    release=json.loads(args.release_json.read_text())
    tag=release.get('tag_name','')
    if not re.fullmatch(r'v\d+\.\d+\.\d+',tag) or release.get('prerelease'): parser.error('stable release metadata required')
    assets={item['name']:item for item in release['assets']}
    selected=[]
    for path in args.archive:
        name=path.name
        if not re.fullmatch(r'mihomo-(?:darwin-(?:arm64|amd64)|linux-(?:arm64|amd64-v1))-'+re.escape(tag)+r'\.gz',name):
            parser.error('unsupported or mismatched archive name')
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if assets.get(name,{}).get('digest')!='sha256:'+digest: parser.error('archive digest differs from upstream metadata')
        target=args.output/'mihomo'/tag/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,target)
        selected.append({'name':name,'digest':'sha256:'+digest,'browser_download_url':base+'mihomo/'+tag+'/'+name})
    metadata={'tag_name':tag,'prerelease':False,'assets':selected}
    for name in ['latest.json',tag+'.json']:
        (args.output/'mihomo'/name).write_text(json.dumps(metadata,indent=2)+'\n')
    if args.geo_dir:
        files={}
        for name in ['Country.mmdb','geoip.dat','geosite.dat','ASN.mmdb']:
            source=args.geo_dir/name
            if not source.is_file(): continue
            target=args.output/'geo'/name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,target)
            files[name]={'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
        (args.output/'geo').mkdir(parents=True,exist_ok=True)
        (args.output/'geo/index.json').write_text(json.dumps({'schema_version':1,'files':files},indent=2)+'\n')
    print(json.dumps({'published':False,'version':tag,'architectures':len(selected),'output':str(args.output)}))


if __name__=='__main__': main()
