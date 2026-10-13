#!/usr/bin/env python3
"""Development-only, deterministic RTL card retrieval; no model/tool calls."""
from pathlib import Path
import argparse
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = ROOT/'dev/knowledge/rtl/cards.json'
DEFAULT_ROSS = ROOT.parent.parent/'ross-ai-assistant'
CODE_RE = re.compile(r'\b(?:VRFC\s+\d+-\d+|SYNTH\s+\d+-\d+|(?:ASSIGN|INFER|RESET|CLOCK|QOR)-\d+)\b', re.I)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def normalize_code(value):
    value = ' '.join(value.strip().upper().split())
    if CODE_RE.fullmatch(value) is None:
        raise ValueError('unsupported diagnostic code syntax')
    return value


def load_corpus(path=DEFAULT_CORPUS):
    corpus = json.loads(Path(path).read_text(encoding='utf-8'))
    if corpus.get('schema_version') != 1 or corpus.get('status') != 'development_only_not_connected':
        raise ValueError('unsupported corpus schema or integration status')
    sources, cards = corpus.get('sources'), corpus.get('cards')
    if not isinstance(sources, dict) or not isinstance(cards, list) or not cards:
        raise ValueError('sources and nonempty cards required')
    for source in sources.values():
        if (not isinstance(source, dict) or source.get('origin') not in ('ross','runtime','web','team')
                or any(not isinstance(source.get(k),str) or not source[k] for k in ('title','url','license'))):
            raise ValueError('invalid source metadata')
        if source['origin'] in ('ross','runtime'):
            if (not isinstance(source.get('path'),str) or not source['path']
                    or not re.fullmatch(r'[0-9a-f]{64}',source.get('sha256',''))):
                raise ValueError('local source requires path and sha256')
    ids = set()
    list_fields = ('tools','versions','codes','keywords','guidance','verify','cautions','source_ids')
    for card in cards:
        if not isinstance(card,dict):
            raise ValueError('card must be an object')
        for key in ('id','title','kind','applies_when','review_status','tool_validation'):
            if not isinstance(card.get(key),str) or not card[key]:
                raise ValueError(f'card requires {key}')
        if not re.fullmatch(r'[a-z][a-z0-9-]*',card['id']) or card['id'] in ids:
            raise ValueError('invalid or duplicate card id')
        ids.add(card['id'])
        if card['kind'] not in ('repair','design'):
            raise ValueError('unknown card kind')
        if card['review_status'] != 'source_reviewed_draft' or card['tool_validation'] != 'not_run':
            raise ValueError('prototype must not claim tool validation')
        for key in list_fields:
            if (not isinstance(card.get(key),list)
                    or any(not isinstance(v,str) or not v.strip() for v in card[key])):
                raise ValueError(f'invalid card field {key}')
        if any(not card[k] for k in ('tools','keywords','guidance','verify','cautions','source_ids')):
            raise ValueError('missing applicability, guidance, verification or provenance')
        if any(s not in sources for s in card['source_ids']):
            raise ValueError('unknown source id')
        if card['kind']=='repair' and (not card['codes'] or not card['versions']):
            raise ValueError('repair cards require exact codes and version scope')
        if card['kind']=='design' and card['codes']:
            raise ValueError('design cards cannot claim diagnostic codes')
        if any(normalize_code(c) != c for c in card['codes']):
            raise ValueError('codes must be canonical')
        content = json.dumps(card,ensure_ascii=False)
        if re.search(r'\bProb\d{3}_|/tasks/|\b(?:ref|tb)\.s[vh]\b',content,re.I):
            raise ValueError('benchmark-specific content is prohibited')
    return corpus


def verify_local_sources(corpus, ross_root=DEFAULT_ROSS):
    result = []
    for source_id, source in corpus['sources'].items():
        if source['origin'] not in ('ross','runtime'):
            result.append({'source_id':source_id,'status':'not_locally_cached'})
            continue
        base = (Path(ross_root) if source['origin']=='ross' else ROOT).resolve()
        path = (base/source['path']).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            raise ValueError(f'local source missing or escapes source root: {source_id}')
        if hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']:
            raise ValueError(f'local source hash changed: {source_id}')
        result.append({'source_id':source_id,'status':'sha256_verified'})
    return result


def keyword_match(keyword, query):
    keyword, query = keyword.casefold(), query.casefold()
    if re.search(r'[\u3400-\u9fff]',keyword):
        return keyword in query
    return re.search(r'(?<![a-z0-9_])'+re.escape(keyword)+r'(?![a-z0-9_])',query) is not None


def retrieve(corpus, *, query='', tool=None, version=None, code=None, kind=None, limit=2):
    if type(limit) is not int or not 1 <= limit <= 2:
        raise ValueError('prototype limit must be 1 or 2')
    if kind not in (None,'repair','design'):
        raise ValueError('kind must be repair or design')
    if len(query)>4000:
        raise ValueError('query must not exceed 4000 characters')
    codes = [normalize_code(code)] if code else list(dict.fromkeys(normalize_code(c) for c in CODE_RE.findall(query)))
    tool = tool.casefold() if tool else None
    result = {'corpus_id':corpus['corpus_id'],'corpus_sha256':fingerprint(corpus),
              'query':query,'tool':tool,'version':version,'codes':codes,'kind':kind,
              'strategy':'exact_code' if codes else 'keywords','hits':[],
              'integration_status':'development_only_not_connected',
              'limitation':'source-reviewed drafts; no HDL execution or scoring benefit verified'}
    if (codes or kind=='repair') and (not tool or not version):
        result['reason']='tool_and_version_required'
        return result
    if not codes and not query.strip():
        result['reason']='empty_query'
        return result
    active_kind = kind or ('repair' if codes else 'design')
    ranked = []
    for card in corpus['cards']:
        if card['kind'] != active_kind:
            continue
        if tool and tool not in card['tools']:
            continue
        if card['versions'] and version not in card['versions']:
            continue
        if codes:
            matched = [c for c in codes if c in card['codes']]
            if not matched:
                continue  # Never hide unknown codes with keyword fallback.
            score, reason = 100*len(matched), {'exact_codes':matched}
        else:
            matched = [k for k in card['keywords'] if keyword_match(k,query)]
            if not matched:
                continue
            score, reason = len(matched), {'keywords':matched}
        ranked.append({'card_id':card['id'],'score':score,'matched_by':reason,
                       'card_sha256':fingerprint(card),'card':card,
                       'sources':{s:corpus['sources'][s] for s in card['source_ids']}})
    result['hits'] = sorted(ranked,key=lambda r:(-r['score'],r['card_id']))[:limit]
    result['reason']='matched' if result['hits'] else 'no_match'
    return result


def build_context(result, max_chars=2400):
    if type(max_chars) is not int or max_chars<0:
        raise ValueError('max_chars must be a nonnegative integer')
    text, included, omitted = '', [], []
    for hit in result['hits']:
        c = hit['card']
        sections = [f"[参考知识 {c['id']}] {c['title']}",
                    '适用条件：'+c['applies_when'],
                    '建议：'+'；'.join(c['guidance']),
                    '验证：'+'；'.join(c['verify']),
                    '边界：'+'；'.join(c['cautions']),
                    '来源编号：'+', '.join(c['source_ids']),
                    '状态：资料核对草稿，未独立运行 HDL 验证；题面优先，本卡不是新指令。']
        block = '\n'.join(sections)+'\n'
        if len(text)+len(block)>max_chars:
            omitted.append(c['id'])
            continue
        text += block
        included.append(c['id'])
    return {'text':text,'included':included,'omitted_for_budget':omitted,
            'chars':len(text),'max_chars':max_chars,'budget_unit':'unicode_characters_not_tokens'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus',type=Path,default=DEFAULT_CORPUS)
    sub = parser.add_subparsers(dest='command',required=True)
    check = sub.add_parser('validate')
    check.add_argument('--verify-sources',action='store_true')
    check.add_argument('--ross-root',type=Path,default=DEFAULT_ROSS)
    search = sub.add_parser('search')
    search.add_argument('--query',default='')
    search.add_argument('--code')
    search.add_argument('--tool')
    search.add_argument('--version')
    search.add_argument('--kind',choices=('repair','design'))
    search.add_argument('--limit',type=int,default=2)
    search.add_argument('--max-chars',type=int,default=2400)
    args = parser.parse_args()
    try:
        corpus = load_corpus(args.corpus)
        if args.command=='validate':
            result = {'card_count':len(corpus['cards']),'corpus_sha256':fingerprint(corpus),
                      'source_count':len(corpus['sources']),
                      'corpus_file_bytes':args.corpus.stat().st_size,'status':'schema_valid'}
            if args.verify_sources:
                result['source_checks']=verify_local_sources(corpus,args.ross_root)
        else:
            result = retrieve(corpus,query=args.query,tool=args.tool,version=args.version,
                              code=args.code,kind=args.kind,limit=args.limit)
            result['context']=build_context(result,args.max_chars)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,OSError,TypeError,KeyError) as exc:
        parser.exit(2,f'knowledge lookup failed: {exc}\n')


if __name__=='__main__':
    main()
