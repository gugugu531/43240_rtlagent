#!/usr/bin/env python3
"""统一题型、估计难度和质量门槛，生成可复现的均衡题集。"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import shlex
import sys

from datasets import ROOT, DATA, TASKS, check_task, code_only, write_json
from validate_datasets import fingerprint

CATEGORIES = {
    'logic': '组合逻辑与布尔推导', 'arithmetic': '算术运算',
    'sequential': '寄存器、移位与边沿', 'counter': '计数与定时',
    'fsm': '状态机与协议识别', 'memory': '存储器与队列',
    'interface': '跨时钟域与数据接口', 'processor': '处理器部件',
    'dsp': '并行计算与信号处理', 'crypto': '密码运算',
}
DIFFICULTIES = {'basic': '基础', 'intermediate': '进阶', 'advanced': '复杂'}
HIGH_VE = {128,137,140,141,143,144,146,150,151,152,153,154,155,156}

# 按逐题题面核对的主考点；内部出现counter/FSM并不改变算术题的主分类。
RTLLM_GROUPS = {
 'arithmetic': 'accu adder_8bit adder_16bit adder_32bit adder_bcd adder_pipe_64bit sub_64bit multi_8bit multi_16bit multi_booth_8bit multi_pipe_4bit multi_pipe_8bit div_16bit radix2_div fixed_point_adder fixed_point_substractor float_multi pe',
 'logic': 'comparator_3bit comparator_4bit barrel_shifter',
 'sequential': 'right_shifter lfsr edge_detect',
 'counter': 'counter_12 jc_counter ring_counter up_down_counter calendar freq_div freq_divbyeven freq_divbyodd freq_divbyfrac square_wave clkgenerator signal_generator',
 'fsm': 'fsm sequence_detector traffic_light',
 'memory': 'asyn_fifo lifobuffer ram rom',
 'interface': 'width_8to16 synchronizer pulse_detect parallel2serial serial2parallel',
 'processor': 'alu instr_reg',
}
RTLLM_BASIC = set('adder_8bit comparator_3bit comparator_4bit right_shifter lfsr edge_detect counter_12 jc_counter ring_counter instr_reg ram rom'.split())
RTLLM_ADVANCED = set('asyn_fifo float_multi radix2_div div_16bit multi_booth_8bit multi_16bit multi_pipe_8bit adder_pipe_64bit synchronizer'.split())
CHIP_SELF = {
 0:('logic','basic'),1:('fsm','intermediate'),2:('fsm','intermediate'),3:('fsm','intermediate'),
 4:('fsm','intermediate'),5:('counter','intermediate'),6:('interface','intermediate'),
 7:('arithmetic','intermediate'),8:('interface','advanced'),9:('interface','advanced'),
 10:('interface','intermediate'),11:('arithmetic','intermediate'),12:('fsm','intermediate'),
 13:('arithmetic','advanced'),14:('sequential','intermediate'),15:('fsm','intermediate'),
 16:('counter','intermediate'),17:('counter','advanced'),20:('fsm','intermediate'),
 23:('counter','basic'),24:('arithmetic','intermediate'),25:('interface','advanced'),
 26:('counter','intermediate'),27:('counter','intermediate'),28:('counter','intermediate'),
 30:('memory','intermediate'),31:('counter','basic'),32:('arithmetic','advanced'),
 33:('fsm','intermediate'),34:('counter','intermediate'),
}


def annotate(tid, prompt):
    """规则只读题面与题号；标签不是实测模型通过率。"""
    low=prompt.lower()
    name=re.sub(r'^(?:verilogeval|chipbench|rtllm|example|archxbench)_', '', tid)
    combined=name+'\n'+low
    tags=[]
    for tag,pat in [('waveform',r'waveform'),('bugfix',r'bugs_|fix the|correct the|bug'),
                    ('parameterized',r'parameter\s|parameteriz'),('hierarchical',r'submodule|sub-module|instantiate'),
                    ('signed',r'signed|two.s complement'),('pipeline',r'pipelin'),
                    ('multi_clock',r'wclk|rclk|clock domains|clock domain')]:
        if re.search(pat,combined): tags.append(tag)
    if 'aes_encryption' in tid:
        cat,reason='crypto','AES密钥扩展及十轮流水线'
    elif re.search(r'systolic|convolution|fft|\bfir\b|conwaylife',combined):
        cat,reason='dsp','空间并行或信号处理'
    elif 'cpu_ip' in tid or re.search(r'gshare|cpu_top|branch predictor|program counter',combined):
        cat,reason='processor','处理器控制、运算或预测部件'
    elif re.search(r'fifo|lifo|\bram\b|\brom\b|register file',combined):
        cat,reason='memory','存储、读写或队列边界'
    elif re.search(r'synchroniz|width_8to16|serial2parallel|parallel2serial|width_conversion|data_serial-to-parallel|pulse_detect|pulse_synchronization',combined):
        cat,reason='interface','跨时钟域、握手或数据宽度转换'
    elif re.search(r'fsm|lemmings|state machine|state diagram|sequence detect|detect the sequence|detect_1101|vending|traffic_light',combined):
        cat,reason='fsm','状态转移或协议时序识别'
    elif re.search(r'counter|timer|stopwatch|calendar|freq_div|frequency div|clock divider|square_wave|clkgenerator|johnson|count\d|countbcd|countslow|count_clock|count1to10|count1k',combined):
        cat,reason='counter','计数、分频或定时控制'
    elif re.search(r'adder|add-subtract|adder-subtractor|subtractor|multiplier|multiplication|divider|div_16|radix2_div|booth|popcount|population count|square root|least.common.multiple|accumulat|\balu\b|_alu',combined):
        cat,reason='arithmetic','数值运算、乘加或迭代算术'
    elif re.search(r'flip.flop|\bdff\b|\bdffs\b|shift register|lfsr|latch|edge detect|edgedetect|edgecapture|rotate|rule ?(?:90|110)|sequential circuit',combined):
        cat,reason='sequential','状态存储、移位或边沿逻辑'
    else:
        cat,reason='logic','组合映射、选择、门逻辑或布尔推导'
    difficulty='intermediate'
    evidence='多个条件、状态或控制信号，需保持时序及优先级'
    if cat=='logic' and 'waveform' not in tags and 'bugfix' not in tags:
        difficulty,evidence='basic','主要为单一组合映射或布尔表达式'
    if re.search(r'\b(?:half|full) adder\b|popcount3|ex01_popcount8|adder_8bit|comparator_[34]bit',combined):
        difficulty,evidence='basic','基础小位宽算术或比较'
    if tid.startswith('verilogeval_'):
        number=int(re.search(r'prob(\d+)',tid)[1])
        if number in HIGH_VE:
            difficulty,evidence='advanced','协议/状态与数据路径组合，或较大并行状态更新'
        elif number<=67 and cat in ('sequential','counter') and 'waveform' not in tags:
            difficulty,evidence='basic','单一寄存器、边沿或基本计数行为'
        elif re.search(r'fsm1s?$|fsm2s?$',name):
            difficulty,evidence='basic','两状态状态机'
    if re.search(r'float_multi|newton_raphson|systolic|aes_encryption|asyn_fifo|asynchronous_fifo|non-integer_data_width|radix2_div|div_16bit|multi_booth|multi_16bit|adder_pipe_64bit|pipeline_multiplier|multi_pipe_8bit|cp0_reg|chapter12_ctrl|cpu_top|cpu_ip_prob007_div',tid):
        difficulty,evidence='advanced','多周期算法、深流水线、跨时钟域队列或复杂系统控制'
    if 'rtllm_' in tid and re.search(r'right_shifter|ring_counter|jc_counter|counter_12|lfsr$|edge_detect|instr_reg|rom$|ram$',tid):
        difficulty,evidence='basic','基础存储、移位、计数或边沿单元'
    if cat in ('dsp','crypto'):
        difficulty,evidence='advanced','并行计算结构或完整密码运算'
    if tid.startswith('rtllm_'):
        key=tid.removeprefix('rtllm_')
        cat=next(c for c,names in RTLLM_GROUPS.items() if key in names.split())
        difficulty='basic' if key in RTLLM_BASIC else 'advanced' if key in RTLLM_ADVANCED else 'intermediate'
        reason='逐题核对主考点：'+CATEGORIES[cat]
    elif tid.startswith('chipbench_self_contain_'):
        cat,difficulty=CHIP_SELF[int(re.search(r'prob(\d+)',tid)[1])]
        reason='逐题核对主考点：'+CATEGORIES[cat]
    elif tid.startswith('chipbench_not_self_contain_'):
        n=int(re.search(r'prob(\d+)',tid)[1])
        cat,difficulty={1:('logic','intermediate'),2:('arithmetic','basic'),3:('memory','advanced'),
                        4:('memory','intermediate'),5:('arithmetic','intermediate'),6:('processor','advanced')}[n]
        reason='逐题核对主考点：'+CATEGORIES[cat]
    elif 'newton_raphson_sqrt' in tid:
        cat,reason='arithmetic','定点除法、缩放和Newton-Raphson迭代'
    elif 'popcount' in tid:
        cat,reason='arithmetic','统计输入置位个数'
        if 'popcount255' in tid:
            difficulty,evidence='intermediate','较宽输入的计数与结果位宽处理'
    if tid.startswith('verilogeval_'):
        overrides={
            33:('arithmetic','intermediate','有符号加法和溢出标志'),
            63:('sequential','intermediate','移位与减计数模式配合'),
            118:('sequential','intermediate','移位历史和流水线回滚优先级'),
            149:('fsm','intermediate','水位控制需要记忆上升或下降趋势'),
        }
        number=int(re.search(r'prob(\d+)',tid)[1])
        if number in overrides:
            cat,difficulty,reason=overrides[number]
            evidence=reason
    if tid.startswith(('chipbench_','rtllm_')):
        evidence={'basic':'单一运算或基本存储/计数单元',
                  'intermediate':'多条件、数据宽度、标志位或状态时序配合',
                  'advanced':'多周期算术、流水线、跨时钟域或复杂系统状态'}[difficulty]
    return dict(category=cat, category_reason=reason, difficulty=difficulty,
                difficulty_basis='specification_estimate', difficulty_reason=evidence, tags=tags)


def mutation_rejected(v):
    # 编译失败不能证明测试台检出了功能错误。
    return (not v.get('tool_error') and v.get('level') == 1 and
            ((v.get('mismatches') or 0)>0 or v.get('sim_timeout') is True))


def eligibility(row, path, validation):
    reasons=[]
    if row.get('format_errors'): reasons.append('format_error')
    if not validation:
        return reasons+['validation_missing']
    if not validation.get('complete'):
        return reasons+['validation_incomplete']
    if validation.get('fingerprint')!=fingerprint(path):
        return reasons+['validation_stale']
    ref=validation.get('reference',{})
    if ref.get('tool_error'): reasons.append('reference_tool_error')
    if ref.get('level')!=3: reasons.append('reference_not_l3')
    mutations=validation.get('mutants',{})
    if not mutation_rejected(mutations.get('unknown',{})):
        reasons.append('unknown_mutant_not_rejected')
    # 这两道题面明确要求恒零，恒零候选不是错误实现。
    constant_zero=bool(re.search(r'verilogeval_prob00[12]_',row['task_id']))
    if not constant_zero and not mutation_rejected(mutations.get('zero',{})):
        reasons.append('zero_mutant_not_rejected')
    return reasons


def distribution(rows):
    return dict(category=dict(sorted(Counter(r['category'] for r in rows).items())),
                difficulty=dict(sorted(Counter(r['difficulty'] for r in rows).items())),
                dataset=dict(sorted(Counter(r['dataset'] for r in rows).items())),
                cells=dict(sorted(Counter(r['category']+'/'+r['difficulty'] for r in rows).items())))


def normalized_reference(path):
    # 仅识别保守的文本重复，不声称证明逻辑等价。
    text=code_only((path/'reference/solution.sv').read_text())
    text=re.sub(r'\s+','',text)
    return hashlib.sha256(text.encode()).hexdigest()


def balanced_selection(rows, size):
    """最小费用流：同时压低题型与难度边际计数的平方和。"""
    cats=sorted({r['category'] for r in rows})
    diffs=sorted(DIFFICULTIES)
    nodes=['source',*('c:'+x for x in cats),*('d:'+x for x in diffs),'sink']
    ids={x:i for i,x in enumerate(nodes)}
    graph=[[] for _ in nodes]
    def edge(u,v,cap,cost,row=None):
        u,v=ids[u],ids[v]
        forward=[v,len(graph[v]),cap,cost,row]
        backward=[u,len(graph[u]),0,-cost,None]
        graph[u].append(forward); graph[v].append(backward)
        return forward
    for cat in cats:
        for i in range(1,1+sum(r['category']==cat for r in rows)):
            edge('source','c:'+cat,1,(2*i-1)*30000)
    for diff in diffs:
        for i in range(1,1+sum(r['difficulty']==diff for r in rows)):
            edge('d:'+diff,'sink',1,(2*i-1)*100000)
    by_cell=defaultdict(list)
    for r in rows: by_cell[r['category'],r['difficulty']].append(r)
    candidate_edges=[]
    for (cat,diff),candidates in sorted(by_cell.items()):
        # 同一单元格按数据集轮换，随后按固定哈希排序，减少题号顺序偏差。
        sources=defaultdict(list)
        for r in candidates: sources[r['dataset']].append(r)
        for group in sources.values(): group.sort(key=lambda r: hashlib.sha256(r['task_id'].encode()).hexdigest())
        ordered=[]
        while any(sources.values()):
            for name in sorted(sources):
                if sources[name]: ordered.append(sources[name].pop(0))
        for rank,r in enumerate(ordered):
            candidate_edges.append(edge('c:'+cat,'d:'+diff,1,rank,r))
    flow=0
    while flow<min(size,len(rows)):
        distance=[float('inf')]*len(nodes); parent=[None]*len(nodes)
        distance[ids['source']]=0
        # 图很小；Bellman-Ford处理残量图上的负费用逆边。
        for _ in range(len(nodes)-1):
            changed=False
            for u,edges in enumerate(graph):
                for i,e in enumerate(edges):
                    v,_,cap,cost,_=e
                    if cap and distance[u]+cost<distance[v]:
                        distance[v]=distance[u]+cost;parent[v]=(u,i);changed=True
            if not changed: break
        v=ids['sink']
        if parent[v] is None: break
        while v!=ids['source']:
            u,i=parent[v];e=graph[u][i]
            e[2]-=1;graph[v][e[1]][2]+=1;v=u
        flow+=1
    return sorted([e[4] for e in candidate_edges if e[2]==0],key=lambda r:r['task_id'])


def selection_report(summary, catalog):
    lines=['# 均衡题集筛选结果', '',
           '类型：自动生成的验证与筛选统计。难度来自题面估计，不是模型实测通过率。', '',
           '不要手改；以下为生成时在仓库根目录执行的命令。筛选只生成TXT清单和统计，不复制题目。', '',
           '```bash', summary['command'], '```', '',
           f"共登记 {len(catalog)} 道来源记录；其中 {summary['converted']} 道已整理为现有格式，"
           f"{summary['deferred']} 道保留未转换原因。质量验证及去重后可用 {summary['eligible']} 道，"
           f"本次选取 {summary['selected']} 道。", '',
           '完整来源和适配记录见 `dev/datasets/conversion.json`；逐题标签、验证结果及排除原因见',
           '`dev/datasets/catalog.json`；入选清单和分布见 `dev/datasets/selection.json`。', '',
           '## 来源覆盖', '', '| 来源 | 已整理 | 未转换 | 合格且去重 | 入选 |', '| --- | ---: | ---: | ---: | ---: |']
    for dataset in sorted({r['dataset'] for r in catalog}):
        rows=[r for r in catalog if r['dataset']==dataset]
        values=[sum(r['status']=='converted' for r in rows),sum(r['status']!='converted' for r in rows),
                sum(r['eligible'] for r in rows),summary['after']['dataset'].get(dataset,0)]
        lines.append('| '+dataset+' | '+' | '.join(map(str,values))+' |')
    for field,title,labels in [('category','题型分布',CATEGORIES),('difficulty','估计难度分布',DIFFICULTIES)]:
        lines += ['', '## '+title, '', '| 类别 | 整理后全池 | 合格且去重 | 入选 |', '| --- | ---: | ---: | ---: |']
        for key,label in labels.items():
            values=[summary[stage][field].get(key,0) for stage in ('before','eligible_distribution','after')]
            lines.append('| '+label+' | '+' | '.join(map(str,values))+' |')
    lines += ['', '## 排除原因', '', '同一道题可能有多个原因，以下数量不能直接相加。', '',
              '| 原因 | 数量 |', '| --- | ---: |']
    for reason,count in sorted(summary['exclusions'].items()):
        lines.append(f'| `{reason}` | {count} |')
    lines += ['', '## 覆盖缺口', '', '下列题型与难度组合没有合格候选，不补造题目：', '']
    lines += ['- '+CATEGORIES[c]+' / '+DIFFICULTIES[d] for c,d in (cell.split('/') for cell in summary['uncovered_cells'])]
    lines += ['', '质量门槛、上游版本、ArchXBench 本地参考实现、CVDP 样例范围及复现方法见',
              '[题集说明](../design/datasets.md)。本地改编题的分数不能视为上游官方成绩。', '']
    return '\n'.join(lines)


def build(args):
    raw=json.loads((DATA/'conversion.json').read_text())['tasks']
    overrides=json.loads((DATA/'labels.json').read_text()) if (DATA/'labels.json').exists() else {}
    catalog=[]
    for r in raw:
        row=dict(r)
        if row['status']!='converted':
            row.update(eligible=False, exclusions=['not_converted'])
            catalog.append(row);continue
        path=args.tasks/row['dataset']/row['task_id']
        row['format_errors']=check_task(path)
        row.update(annotate(row['task_id'],(path/'prompt.txt').read_text()))
        custom=overrides.get(row['task_id'],{})
        allowed={'category','category_reason','difficulty','difficulty_reason','tags'}
        if set(custom)-allowed:
            raise ValueError('标签覆盖只允许分类、难度、理由和附加标签：'+row['task_id'])
        row.update(custom)
        if row['category'] not in CATEGORIES or row['difficulty'] not in DIFFICULTIES:
            raise ValueError('未知分类或难度：'+row['task_id'])
        vp=args.validation/row['task_id']/'validation.json'
        validation=json.loads(vp.read_text()) if vp.exists() else None
        row['exclusions']=eligibility(row,path,validation)
        row['eligible']=not row['exclusions']
        row['fingerprint']=fingerprint(path)
        row['validation']={k:validation.get(k) for k in ('reference','mutants')} if validation else None
        row['reference_text_hash']=normalized_reference(path)
        catalog.append(row)
    seen={}
    for r in catalog:
        if not r['eligible']:continue
        key=r['reference_text_hash']
        if key in seen:
            r['eligible']=False;r['exclusions'].append('duplicate_reference:'+seen[key])
        else: seen[key]=r['task_id']
    eligible=[r for r in catalog if r['eligible']]
    selected=balanced_selection(eligible,args.size)
    converted=[r for r in catalog if r['status']=='converted']
    summary=dict(generated=True, command=shlex.join(['python3', *sys.argv]),
                 note='自动生成，不要手改。难度为题面估计，不是模型通过率。原始验证日志位于dev/runs/dataset-validation/full。',
                 requested_size=args.size, converted=len(converted), deferred=len(catalog)-len(converted),
                 eligible=len(eligible), selected=len(selected),
                 before=distribution(converted), eligible_distribution=distribution(eligible), after=distribution(selected),
                 uncovered_cells=[c+'/'+d for c in CATEGORIES for d in DIFFICULTIES
                                  if not any(r['category']==c and r['difficulty']==d for r in eligible)],
                 exclusions=dict(Counter(reason for r in catalog for reason in r['exclusions'])),
                 tasks=[r['task_id'] for r in selected])
    write_json(DATA/'catalog.json',dict(generated=True,tasks=catalog))
    write_json(DATA/'selection.json',summary)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(selection_report(summary,catalog))
    config=args.list
    config.parent.mkdir(parents=True,exist_ok=True)
    config.write_text('# 自动生成：python3 dev/tools/balance_datasets.py --size '+str(args.size)+'\n'+
                      '\n'.join(r['task_id'] for r in selected)+'\n')
    print(json.dumps({k:summary[k] for k in ('converted','deferred','eligible','selected','after')},ensure_ascii=False,indent=2))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tasks',type=Path,default=TASKS)
    ap.add_argument('--validation',type=Path,default=ROOT/'dev/runs/dataset-validation/full')
    ap.add_argument('--size',type=int,default=60)
    ap.add_argument('--list',type=Path,default=ROOT/'dev/configs/balanced.txt',help='输出选题TXT清单')
    ap.add_argument('--report',type=Path,help='生成中文统计；目标须位于dev/docs/')
    args=ap.parse_args()
    if args.size<1:ap.error('--size 必须大于0')
    if not any(args.list.resolve().is_relative_to(root) for root in (ROOT/'dev',TASKS)):
        ap.error('选题清单必须位于tasks/或开发区dev/')
    if args.report and not args.report.resolve().is_relative_to(ROOT/'dev/docs'):
        ap.error('统计文档必须位于dev/docs/')
    build(args)


if __name__=='__main__':main()
