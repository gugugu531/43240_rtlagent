#!/usr/bin/env python3
"""Read existing evidence without inference; write derived diagnostic reports."""
from collections import Counter
from pathlib import Path
import argparse
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agent.nodes.extraction import extract_result
from agent.recording.artifacts import atomic_write_json, atomic_write_text


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def classify_response(response):
    choice = response['choices'][0]
    message = choice['message']
    content = message.get('content') or ''
    reasoning = message.get('reasoning_content') or ''
    unclosed = '<think>' in content and '</think>' not in content
    # Never mistake a draft inside an unfinished thinking block for final RTL.
    final = '' if unclosed else content.rsplit('</think>', 1)[-1]
    extracted = extract_result(final, target_module='TopModule')
    if extracted.complete and extracted.target_module_found:
        category = 'complete_rtl'
    elif choice.get('finish_reason') == 'length' and (unclosed or (reasoning and not content.strip())):
        category = 'thinking_truncated'
    elif extracted.status == 'target_missing':
        category = 'target_module_missing'
    elif extracted.suspected_truncation and choice.get('finish_reason') == 'length':
        category = 'rtl_truncated'
    else:
        category = 'no_extractable_final_rtl'
    return {'category': category, 'finish_reason': choice.get('finish_reason'),
            'unclosed_think': unclosed, 'content_chars': len(content),
            'reasoning_chars': len(reasoning), 'extraction': extracted.trace_dict(),
            'completion_tokens': response.get('usage', {}).get('completion_tokens')}


def inspect_sample(row):
    output = Path(row['output_dir'])
    metrics = {m['name']: m for m in row['metrics']}
    verdict = metrics['judge']['values']['verdict']
    events = [json.loads(l) for l in (output/'trace.jsonl').read_text().splitlines() if l.strip()]
    calls = []
    for path in sorted(output.glob('records/*/calls/*/response.json')):
        response = json.loads(path.read_text())
        request = json.loads((path.parent/'request.json').read_text())
        detail = classify_response(response)
        detail.update(call_id=path.parent.name, response_path=str(path),
                      response_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                      messages_sha256=digest(request['messages']), purpose=request['purpose'],
                      requested_max_tokens=request['max_tokens'],
                      requested_temperature=request['temperature'], requested_top_p=request['top_p'])
        detail['production_extraction'] = next((e for e in events if
            e.get('tool') == 'extract' and e.get('call_id') == path.parent.name), None)
        calls.append(detail)
    level = verdict['level']
    if verdict.get('tool_error') or row['solve']['status'] != 'ok':
        category = 'infrastructure_error'
    elif level >= 2:
        category = 'functional_pass'
    elif level == 1:
        category = 'functional_error'
    elif calls and all(c['category'] == 'thinking_truncated' for c in calls):
        category = 'thinking_truncation_no_candidate'
    elif (output/'solution.v').stat().st_size:
        category = 'code_or_interface_error'
    else:
        category = 'generation_or_extraction_failure'
    return {'task_id': row['task_id'], 'mode': row['mode'], 'level': level,
            'category': category, 'output_dir': str(output), 'calls': calls,
            'raw_response_available': bool(calls),
            'model_metrics': metrics['model']['values'], 'solve': row['solve'],
            'verdict': verdict}


def offline(combined):
    rows = json.loads((combined/'metrics.json').read_text())
    paired = {}
    for row in rows:
        paired.setdefault(row['task_id'], {})[row['mode']] = row
    regressions = []
    for task, modes in sorted(paired.items()):
        def level(mode):
            return next(m for m in modes[mode]['metrics'] if m['name'] == 'judge')['values']['verdict']['level']
        if level('agent') < level('baseline'):
            regressions.append({'task_id': task,
                                'agent': inspect_sample(modes['agent']),
                                'baseline': inspect_sample(modes['baseline'])})
    return {'kind': 'offline_no_inference', 'source': str(combined),
            'tool_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'regressions': regressions,
            'agent_categories': dict(Counter(r['agent']['category'] for r in regressions)),
            'limitation': 'Historical baseline did not save raw responses; do not infer its thinking text.'}


def markdown(report):
    lines = ['# 五道退步题：离线响应诊断', '',
             '本文件由 `python3 dev/tools/generation_diagnostic.py offline --combined <combined目录> --out <新目录>` 生成，不要手改。',
             '只读取已有响应、代码与判定记录，没有调用模型或启动 GPU。逐调用路径、哈希与分类见同目录 report.json。', '',
             '| 题目 | Agent / baseline | Agent 失败分类 | 逐调用生成情况 |',
             '| --- | --- | --- | --- |']
    for r in report['regressions']:
        a, b = r['agent'], r['baseline']
        calls = '；'.join(f"{c['call_id']}: {c['category']} ({c['completion_tokens']} tokens)" for c in a['calls'])
        lines.append(f"| {r['task_id']} | L{a['level']} / L{b['level']} | {a['category']} | {calls} |")
    lines.extend(['', '分类说明：thinking_truncated 是思考未结束便耗尽输出预算；complete_rtl 只表示完整目标模块可提取，不表示语法或功能正确。',
                  '本组没有证据证明“完整的最终 RTL 已输出但被生产提取器丢失”；不要将没有最终代码统称为提取器故障。',
                  '旧 baseline 没保存原始响应，只能核对 trace 中的 finish/tokens 和最终代码，不能声称复查了其思考原文。',
                  '题集按已知退步结果选择，只用于诊断，不代表独立泛化评测。', ''])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    off = sub.add_parser('offline')
    off.add_argument('--combined', type=Path, required=True)
    off.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = offline(args.combined)
    args.out.mkdir(parents=True, exist_ok=False)
    atomic_write_json(args.out/'report.json', report)
    atomic_write_text(args.out/'README.md', markdown(report))
    print(args.out)


if __name__ == '__main__':
    main()
