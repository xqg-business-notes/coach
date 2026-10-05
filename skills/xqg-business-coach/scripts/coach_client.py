#!/usr/bin/env python3
"""Query Business Coach. No bundled knowledge, shared credentials, or chat upload."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import stat
from urllib.request import Request, HTTPRedirectHandler, build_opener
from urllib.error import HTTPError, URLError

BASE_URL='https://api.xqgnetwork.com/coach/v1'
CLIENT_VERSION='0.2.0-rc7'
CLIENT_PROTOCOL=1


def version_tuple(value):
    if not isinstance(value,str):return None
    match=re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:-rc(\d+))?',value)
    if not match:return None
    major,minor,patch,rc=match.groups()
    return (int(major),int(minor),int(patch),rc is None,int(rc or 0))


def update_metadata(data):
    latest=data.get('client_latest')
    newer=version_tuple(latest) is not None and version_tuple(latest)>version_tuple(CLIENT_VERSION)
    minimum=data.get('minimum_protocol')
    required=type(minimum) is int and minimum>CLIENT_PROTOCOL
    return dict(client_version=CLIENT_VERSION,update_available=newer,update_required=required)


def http_failure(error):
    statuses={401:'connection_denied',403:'connection_denied',422:'question_scope_required',429:'query_limit_reached',426:'client_update_required'}
    status=statuses.get(error.code,'service_unavailable')
    try:
        data=json.loads(error.read(4097))
        if error.code==429 and isinstance(data,dict) and data.get('status')=='knowledge_access_limit':status='knowledge_access_limit'
    except (OSError,ValueError,TypeError):pass
    finally:error.close()
    return {'status':status,'http_status':error.code}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def installation_token():
    folder=Path.home()/'.config/xqg-business-coach'
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    if folder.is_symlink() or folder.stat().st_mode & 0o077:raise ValueError('unsafe identity directory')
    path=folder/'installation.key'
    try:
        fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream:stream.write(secrets.token_urlsafe(32))
    except FileExistsError:pass
    if path.is_symlink():raise ValueError('unsafe identity file')
    fd=os.open(str(path),os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
    with os.fdopen(fd) as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:raise ValueError('unsafe identity file')
        token=stream.read(129).strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):raise ValueError('invalid identity')
    return token


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('status')
    query=sub.add_parser('query');query.add_argument('--question',required=True)
    query.add_argument('--decision',help='当前要做的决定，4至200字；背景限制仍保留在question中')
    args=parser.parse_args()
    try:
        payload={}
        if args.command=='query':
            question=args.question.strip()
            if not 8<=len(question)<=800:raise ValueError('question must contain 8 to 800 characters')
            payload={'question':question}
            if args.decision is not None:
                decision=args.decision.strip()
                if not 4<=len(decision)<=200:raise ValueError('decision must contain 4 to 200 characters')
                payload['decision']=decision
        endpoint='capabilities' if args.command=='status' else 'query'
        req=Request(BASE_URL+'/'+endpoint,data=json.dumps(payload,ensure_ascii=False).encode(),headers={'Content-Type':'application/json','Accept':'application/json','User-Agent':'XQG-Business-Coach/'+CLIENT_VERSION,'Authorization':'Bearer '+installation_token()},method='POST')
        with build_opener(NoRedirect).open(req,timeout=15) as response:raw=response.read(65537)
        if len(raw)>65536:raise ValueError('response too large')
        data=json.loads(raw)
        if not isinstance(data,dict) or data.get('status')!='ok':raise ValueError('unexpected response')
        out={k:data[k] for k in ['status','product','api_version','knowledge_version','retrieval_mode','query_available','conversation_storage','client_latest','minimum_protocol','scope'] if k in data}
        if endpoint=='capabilities':
            out.update(update_metadata(data))
            if out['update_required']:
                out['status']='client_update_required'
                print(json.dumps(out,ensure_ascii=False,indent=2));return 1
        if endpoint=='query':
            out['methods']=[]
            for item in data.get('methods',[])[:3]:
                if not isinstance(item,dict):continue
                sources=[]
                for link in item.get('sources',[])[:4]:
                    if isinstance(link,dict) and str(link.get('url','')).startswith('https://'):
                        sources.append({'title':str(link.get('title',''))[:200],'url':str(link['url'])[:1000]})
                method={'title':str(item.get('title',''))[:300],'method':str(item.get('method',''))[:1500],'sources':sources}
                if item.get('basis') in ('method','source_summary'):method['basis']=item['basis']
                out['methods'].append(method)
        print(json.dumps(out,ensure_ascii=False,indent=2));return 0
    except HTTPError as error:
        print(json.dumps(http_failure(error),ensure_ascii=False));return 1
    except (OSError,ValueError,TypeError,URLError,TimeoutError) as error:
        print(json.dumps({'status':'service_unavailable','reason':type(error).__name__},ensure_ascii=False));return 1


if __name__=='__main__':raise SystemExit(main())
