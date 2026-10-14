#!/usr/bin/env python3
"""开发区题集转换、来源登记；不会读取模型或调用求解流程。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent
DATA = ROOT / 'dev/datasets'
sys.path.insert(0, str(ROOT))
from agent.core.interface import parse_module_interface

SOURCES = {
    'chipbench': ('https://github.com/zhongkaiyu/ChipBench', 'b4ba3a06759804ec88c26c3cf15b28b9a90b3443'),
    'rtllm': ('https://github.com/hkust-zhiyao/RTLLM', '51ed553d0ffd32797a1a0a13e051656bf302c81f'),
    'archxbench': ('https://github.com/sureshpurini/ArchXBench', '0db0d0de25aad5238393d51bd97ce952e579fa1a'),
    'cvdp': ('https://github.com/NVlabs/cvdp_benchmark', '8e894cf74414ab1eaea1e2b4e80a02f123df07b6'),
}
TOKEN = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\b[A-Za-z_]\w*\b', re.S)
MODULE = re.compile(r'\bmodule\s+(\w+)\b')


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code_only(text):
    return re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"', lambda m: ' ' * len(m[0]), text, flags=re.S)


def rename(text, mapping):
    """仅替换代码标识符，不改注释和字符串。"""
    return TOKEN.sub(lambda m: mapping.get(m[0], m[0]), text)


def module_names(text):
    return MODULE.findall(code_only(text))


def namespaced(text, top, new_top, prefix):
    return rename(text, {n: new_top if n == top else prefix + n for n in module_names(text)})


def source_record(dataset, paths, base):
    url, commit = SOURCES[dataset]
    return dict(dataset=dataset, url=url, commit=commit,
                files={str(p.relative_to(base)): digest(p) for p in paths})


def save_task(out, task_id, prompt, ref, tb, solution, provenance, adaptations):
    dest = out / task_id
    dest.mkdir(parents=True, exist_ok=True)
    (dest / 'reference').mkdir(exist_ok=True)
    for name, text in {'prompt.txt': prompt, 'top.txt': 'TopModule', 'ref.sv': ref,
                       'tb.sv': tb, 'reference/solution.sv': solution}.items():
        (dest / name).write_text(text.rstrip() + '\n')
    meta = dict(task_id=task_id, top='TopModule', part='xczu3eg-sbva484-1-e',
                period_ns=5, reference_module='ref.sv', testbench='tb.sv', tb_top='tb',
                extra_files=[], reference='reference/solution.sv', source=provenance,
                adaptations=adaptations)
    write_json(dest / 'task.json', meta)
    return dict(task_id=task_id, dataset=provenance['dataset'], status='converted',
                source=provenance, adaptations=adaptations)


def convert_chipbench(base, out):
    records = []
    for p in sorted((base / 'Verilog Gen').glob('*/*_prompt.txt')):
        name = p.name.removesuffix('_prompt.txt')
        group = p.parent.name.removeprefix('dataset_')
        tid = 'chipbench_' + group + '_' + name.lower()
        rp, tp = p.with_name(name + '_ref.sv'), p.with_name(name + '_test.sv')
        prompt, ref, tb = p.read_text(), rp.read_text(), tp.read_text()
        changes = ['参考侧子模块独立命名，避免待测实现借用参考侧子模块']
        # 部分层次题的参考文件依赖题面公开给出的子模块。
        for m in re.finditer(r'\bmodule\s+(\w+)\s*(?=[#(]).*?\bendmodule\b', prompt, re.S):
            if m[1] not in module_names(ref):
                ref += '\n' + m[0] + '\n'
                changes.append('补入题面公开子模块 ' + m[1])
        # 上游 Icarus 一次编译测试台和参考；本地先独立编译候选，参考必须自带宏。
        defines = '\n'.join(dict.fromkeys(re.findall(r'(?m)^[ \t]*`define[^\n]+', tb + '\n' + prompt)))
        if defines:
            ref = defines + '\n' + ref
            changes.append('补入上游测试台及题面宏定义，仅用于参考答案独立编译')
        if 'Mismatches:' not in tb:
            old = 'Hint: Total mismatched samples is %1d out of %1d samples.'
            if old not in tb:
                raise ValueError(f'{tid}: 未知统计格式')
            tb = tb.replace(old, 'Mismatches: %1d in %1d samples')
            tb = tb.replace('$display("Hint: No mismatched samples.");',
                            '$display("Mismatches: 0 in %1d samples", stats1.clocks);')
            changes.append('沿用上游统计变量，统一最终统计行')
        # 波形不参与判分，避免大量磁盘输出及前向引用兼容问题。
        tb = re.sub(r'\$(?:dumpfile|dumpvars)\([^;]*\);', '', tb)
        solution = namespaced(ref, 'RefModule', 'TopModule', 'solution_')
        ref = namespaced(ref, 'RefModule', 'RefModule', 'reference_')
        records.append(save_task(out, tid, prompt, ref, tb, solution,
                       source_record('chipbench', [p, rp, tp], base), changes))
    return records


def rtllm_testbench(text, old_top):
    """保留上游激励及断言；一个完整测试台判定计为一个样本。"""
    text = rename(text, {old_top: 'TopModule'})
    first = module_names(text)[0]
    text = rename(text, {first: 'tb'})
    if '`timescale' not in code_only(text):
        text = '`timescale 1ns/1ps\n' + text
    # 逐个语句处理，避开注释中的 display，不依赖单行排版。
    pattern = re.compile(r'\$display\s*\(\s*"((?:\\.|[^"\\])*)".*?\)\s*;', re.S)
    masked = code_only(text)
    pieces, end, passed = [], 0, 0
    for m in pattern.finditer(text):
        if masked[m.start():m.start()+8] != '$display':
            continue
        msg = m[1].lower()
        statement = m[0]
        if 'your design passed' in msg:
            passed += 1
            statement = 'begin ' + statement + ' benchmark_done(1); end'
        elif 'test completed' in msg or ('===' in msg and re.search(r'error|fail', msg)):
            statement = 'begin ' + statement + ' benchmark_done(0); end'
        elif re.search(r'\b(error|failed|timeout)\b', msg):
            # ring_counter 等题失败后仍打印 Passed，需要保留先前失败。
            statement = 'begin tb.benchmark_error = 1; ' + statement + ' end'
        pieces.append(text[end:m.start()] + statement)
        end = m.end()
    if passed != 1:
        raise ValueError(f'成功出口数量应为 1，实际为 {passed}')
    text = ''.join(pieces) + text[end:]
    declarations = '''
    // 转换器新增：一个样本表示一次完整上游测试台判定。
    integer benchmark_error = 0;
    integer benchmark_completed = 0;
    task benchmark_done(input integer passed);
      begin
        benchmark_completed = 1;
        $display("Mismatches: %0d in 1 samples", (!passed || benchmark_error != 0));
        $finish;
      end
    endtask
    final begin
      if (!benchmark_completed)
        $display("Mismatches: 1 in 0 samples");
    end
    initial begin
      #100000000;
      $display("TIMEOUT: upstream testbench did not complete");
      $finish;
    end
'''
    match = re.search(r'\bmodule\s+tb\s*(?:\(\s*\))?\s*;', text)
    if not match:
        raise ValueError('测试台顶层声明不支持')
    return text[:match.end()] + declarations + text[match.end():]


def convert_rtllm(base, out):
    records = []
    for p in sorted(base.rglob('design_description.txt')):
        rp = next(p.parent.glob('verified_*.v'))
        tp = p.parent / 'testbench.v'
        ref, prompt, tb = rp.read_text(), p.read_text(), tp.read_text()
        extra_sources = []
        # 官方判定器只编译三个文件，不复制 extra_files；将上游固定测试数据嵌入原位置。
        def embed_memory(m):
            data = p.parent / m[1]
            extra_sources.append(data)
            words = re.sub(r'//[^\n]*', '', data.read_text()).split()
            if any(not re.fullmatch('[0-9a-fA-FxXzZ_]+', x) for x in words):
                raise ValueError(f'{data}: 不支持的存储器初始化格式')
            return '\n'.join(f"{m[2]}[{i}] = 'h{word};" for i,word in enumerate(words))
        tb = re.sub(r'\$readmemh\("([^"]+)"\s*,\s*(\w+)\);', embed_memory, tb)
        if p.parent.name == 'multi_booth_8bit':
            data = p.parent/'test_data.dat'
            extra_sources.append(data)
            values = [int(x) for x in data.read_text().split()]
            if len(values) != 1+2*values[0]:
                raise ValueError('Booth测试向量数量不符')
            start = tb.index('        fp = $fopen')
            end = tb.index('        if (err > 0)', start)
            tb = tb[:start] + '\n'.join(f'        apply_and_check({a}, {b});' for a,b in zip(values[1::2],values[2::2])) + '\n' + tb[end:]
        mods = module_names(ref)
        # verified_ 前缀只用于上游参考；少数文件名与模块名不一致。
        tops = [n for n in mods if n.startswith('verified_')]
        top = tops[0] if len(tops) == 1 else mods[0]
        # 由实际测试台例化定位待测名称，不从文件名猜测。
        candidates = [n for n in (top.removeprefix('verified_'), p.parent.name)
                      if re.search(r'\b' + re.escape(n) + r'\s*(?:#\s*\(|\w+\s*\()', code_only(tb))]
        if not candidates:
            raise ValueError(f'{p}: 无法定位待测实例')
        dut_name = candidates[0]
        tb = rtllm_testbench(tb, dut_name)
        if p.parent.name == 'freq_divbyeven':
            # checker 在 Verilog 中可用，但在现有 -sv 判定模式中是保留字。
            tb = rename(tb, {'checker': 'divider_checker_instance'})
        prompt = re.sub(r'\b' + re.escape(dut_name) + r'\b', 'TopModule', prompt)
        prompt = ('Implement the module named TopModule described below. '
                  'Include every required helper module in your answer.\n\n' + prompt)
        solution = namespaced(ref, top, 'TopModule', 'solution_')
        ref = namespaced(ref, top, 'RefModule', 'reference_')
        adaptations = ['统一顶层为 TopModule / RefModule / tb；子模块分别命名',
                        '保留上游断言；一次完整测试台判定计为一个样本，不代表逐拍覆盖',
                        '失败信息置位，防止失败后无条件打印 Passed 的假通过',
                        '未到达判定出口的提前结束或超时不得通过',
                        '上游外部测试向量按原值嵌入测试台，避免运行目录依赖']
        if p.parent.name == 'freq_divbyeven':
            adaptations.append('将测试台中的checker实例改名，兼容SystemVerilog保留字')
        records.append(save_task(out, 'rtllm_' + p.parent.name.lower(), prompt, ref, tb,
                       solution, source_record('rtllm', [p, rp, tp, *extra_sources], base),
                       adaptations))
    return records


def inventory_archxbench(base):
    rows = []
    for p in sorted(base.glob('level-*/*/problem-description.txt')):
        files = [p, p.parent/'design-specs.txt', p.parent/'tb.v']
        rows.append(dict(task_id='archxbench_' + p.parent.parent.name.replace('-', '_') + '_' + p.parent.name,
                         dataset='archxbench', status='deferred',
                         reason='上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配',
                         source=source_record('archxbench', [x for x in files if x.exists()], base)))
    return rows


def convert_cvdp(base, out):
    """仅转换官方公开带答案样例中的RTL生成任务，不混入验证生成或补丁任务。"""
    records=[]
    for p in sorted((base/'example_dataset').glob('*with_solutions.jsonl')):
        for line in p.read_text().splitlines():
            row=json.loads(line)
            tid=row['id']
            prov=source_record('cvdp',[p],base)
            if tid!='cvdp_copilot_lfsr_0001':
                reason=('题目要求生成测试台或文字解释，输出契约不是RTL模块' if 'nonagentic' in p.name
                        else '题目要求在工程上下文中提交补丁，不能直接等同单模块RTL生成')
                records.append(dict(task_id=tid,dataset='cvdp',status='deferred',reason=reason,source=prov))
                continue
            solution=rename(row['output']['context']['rtl/lfsr_8bit.sv'],{'lfsr_8bit':'TopModule'})
            prompt=row['input']['prompt'].replace('lfsr_8bit','TopModule')
            prompt='Implement a module named TopModule with the following interface:\n\n - input clock\n - input reset\n - input lfsr_seed (8 bits)\n - output lfsr_out (8 bits)\n\n'+prompt
            tb='''`timescale 1ns/1ps
module tb;
reg clock=0,reset=1;
reg [7:0] lfsr_seed=1,expected;
wire [7:0] lfsr_out;
TopModule dut(.clock(clock),.reset(reset),.lfsr_seed(lfsr_seed),.lfsr_out(lfsr_out));
always #5 clock=~clock;
integer errors=0,samples=0,s,j;
reg [255:0] seen;
initial begin
 for(s=1;s<256;s=s+1) begin
   @(negedge clock);lfsr_seed=s;reset=0;#1;
   samples=samples+1;if(lfsr_out!==lfsr_seed) errors=errors+1;
   @(negedge clock);reset=1;expected=s;seen=0;
   for(j=0;j<255;j=j+1) begin
     @(posedge clock);#1;
     expected=(expected>>1)^(expected[0]?8'hb1:8'h00);
     samples=samples+1;
     if(lfsr_out!==expected || lfsr_out===0 || seen[lfsr_out]===1) errors=errors+1;
     seen[lfsr_out]=1;
   end
   samples=samples+1;if(lfsr_out!==lfsr_seed) errors=errors+1;
 end
 $display("Mismatches: %0d in %0d samples",errors,samples);$finish;
end
initial begin #1000000;$display("TIMEOUT");$finish;end
endmodule
'''
            prov['variant']='local_cocotb_to_sv_adapter'
            records.append(save_task(out,tid,prompt,rename(solution,{'TopModule':'RefModule'}),tb,solution,prov,
                            ['保留上游参考RTL和规格，Cocotb改写为独立SystemVerilog测试台',
                             '由原随机种子抽测扩大为全部255个非零种子，逐拍及周期检查；成绩不等同原始CVDP',
                             '仅代表公开样例，不代表完整CVDP题集']))
    return records


def check_task(path):
    meta = json.loads((path/'task.json').read_text())
    errors = []
    expected = dict(task_id=path.name, top='TopModule', reference_module='ref.sv',
                    testbench='tb.sv', tb_top='tb', reference='reference/solution.sv', extra_files=[])
    for key, value in expected.items():
        if meta.get(key) != value:
            errors.append('task.json 字段不符合现有契约：' + key)
    if not isinstance(meta.get('period_ns'), (int, float)) or meta['period_ns'] <= 0:
        errors.append('period_ns 必须是正数')
    if not meta.get('part'):
        errors.append('缺少目标器件 part')
    if errors:
        return errors
    for name in ('prompt.txt', 'top.txt', meta['reference_module'], meta['testbench'], meta['reference']):
        f = path / name
        if not f.is_file() or not f.read_text().strip():
            errors.append('缺少或空文件 ' + name)
    if errors:
        return errors
    if (path/'top.txt').read_text().strip() != 'TopModule':
        errors.append('top.txt 必须指定 TopModule')
    for name, module in ((meta['reference'], 'TopModule'), (meta['reference_module'], 'RefModule'), (meta['testbench'], 'tb')):
        if module not in module_names((path/name).read_text()):
            errors.append(name + ' 缺少 ' + module)
    if 'Mismatches:' not in (path/meta['testbench']).read_text():
        errors.append('缺少判定统计行')
    if (path/'interface.txt').exists():
        errors.append('现有题集契约不提供 interface.txt')
    return errors


def convert(args):
    out = args.out.resolve()
    if not out.is_relative_to(ROOT / 'dev'):
        raise ValueError('参考答案必须留在 dev/')
    if out.exists() and any(out.iterdir()):
        raise ValueError('输出目录非空；使用新的目录，避免覆盖已有题目')
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for dataset in SOURCES:
        base = args.upstream / dataset
        head = subprocess.check_output(['git', '-C', str(base), 'rev-parse', 'HEAD'], text=True).strip()
        if head != SOURCES[dataset][1]:
            raise ValueError(f'{dataset}: 上游版本不符 {head}')
        fn = {'chipbench': convert_chipbench, 'rtllm': convert_rtllm, 'cvdp': convert_cvdp}.get(dataset)
        if fn:
            records += fn(base, out)
        else:
            from archxbench_adapter import convert_archxbench
            converted = convert_archxbench(base, out, (save_task, source_record, rename, DATA))
            converted_ids = {r['task_id'] for r in converted}
            records += converted + [r for r in inventory_archxbench(base) if r['task_id'] not in converted_ids]
        license_path = next(x for x in [base/'LICENSE', base/'LICENSE.md'] if x.is_file())
        dst = DATA / 'licenses' / (dataset + '.txt')
        dst.parent.mkdir(exist_ok=True, parents=True)
        shutil.copyfile(license_path, dst)
        if (base/'NOTICE').exists():
            shutil.copyfile(base/'NOTICE', DATA/'licenses'/(dataset+'-notice.txt'))
    for p in sorted((REPO/'tasks').glob('*/task.json')):
        src = p.parent
        # 统一池使用小写目录名，原始题集保持原样。
        tid = ('verilogeval_' if src.name.startswith('Prob') else 'example_') + src.name.lower()
        shutil.copytree(src, out/tid)
        meta = json.loads(p.read_text())
        meta.update(task_id=tid, original_task_id=src.name)
        write_json(out/tid/'task.json', meta)
        records.append(dict(task_id=tid, dataset='verilogeval' if src.name.startswith('Prob') else 'example',
                            original_task_id=src.name, status='converted',
                            source=dict(path=str(src.relative_to(REPO)),
                                        files={str(f.relative_to(src)): digest(f) for f in sorted(src.rglob('*')) if f.is_file()})))
    for row in records:
        if row['status'] == 'converted':
            row['format_errors'] = check_task(out/row['task_id'])
    write_json(DATA/'conversion.json', dict(command=shlex.join(['python3', *sys.argv]),
               generated=True, note='自动生成，不要手改；尚未证明参考答案或测试台正确。',
               converter_files={str(p.relative_to(ROOT)): digest(p) for p in
                                [Path(__file__), Path(__file__).with_name('archxbench_adapter.py'),
                                 *sorted((DATA/'adapters').rglob('*.sv'))]}, tasks=records))
    print(json.dumps({s: sum(r['status']==s for r in records) for s in ('converted','deferred')}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    p = sub.add_parser('convert')
    p.add_argument('--upstream', type=Path, default=DATA/'upstream')
    p.add_argument('--out', type=Path, default=DATA/'pool')
    args = ap.parse_args()
    convert(args)


if __name__ == '__main__':
    main()
