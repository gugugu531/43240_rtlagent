"""ArchXBench 少量复杂题的本地参考实现与独立测试；明确标为改编版。"""
from __future__ import annotations
import importlib.util
from pathlib import Path
import random
import re


def load_python(path):
    spec = importlib.util.spec_from_file_location('archx_aes_golden', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sbox_byte(x):
    # 与上游查表生成法不同：幂运算求有限域逆元，再做仿射变换。
    def mul(a,b):
        result=0
        for _ in range(8):
            if b & 1: result ^= a
            a = ((a << 1) ^ (0x11b if a & 0x80 else 0)) & 255
            b >>= 1
        return result
    inv=1
    for _ in range(254): inv=mul(inv,x)
    return inv ^ ((inv<<1)|(inv>>7))&255 ^ ((inv<<2)|(inv>>6))&255 ^ ((inv<<3)|(inv>>5))&255 ^ ((inv<<4)|(inv>>4))&255 ^ 0x63


def aes_fixture(base, adapters):
    golden = load_python(base/'scripts/aes128.py')
    assert golden.encrypt_block(bytes.fromhex('00112233445566778899aabbccddeeff'),
                                bytes.fromhex('000102030405060708090a0b0c0d0e0f')).hex() == '69c4e0d86a7b0430d8cdb78070b4c55a'
    assert [sbox_byte(i) for i in range(256)] == golden.SBOX
    source = (adapters/'aes.sv').read_text()
    source = source.replace('// SBOX_CASES\n', '\n'.join(f"8'h{i:02x}: sb=8'h{sbox_byte(i):02x};" for i in range(256))+'\n')
    rng=random.Random(43240)
    pairs=[(bytes.fromhex('00112233445566778899aabbccddeeff'),bytes.fromhex('000102030405060708090a0b0c0d0e0f'))]
    pairs += [(bytes([i]*16),bytes([j]*16)) for i,j in [(0,0),(255,255),(0,255),(255,0)]]
    pairs += [(rng.getrandbits(128).to_bytes(16,'big'),rng.getrandbits(128).to_bytes(16,'big')) for _ in range(59)]
    init='\n'.join(f"pt[{i}]=128'h{p.hex()}; ky[{i}]=128'h{k.hex()}; expected[{i}]=128'h{golden.encrypt_block(p,k).hex()};" for i,(p,k) in enumerate(pairs))
    tb='''`timescale 1ns/1ps
module tb;
reg clk=0, rst=1, start=0, valid_in=0;
reg [127:0] data_in=0,key_in=0;
wire [127:0] data_out;
wire valid_out,done;
TopModule dut(.clk(clk),.rst(rst),.start(start),.mode(1'b0),.valid_in(valid_in),
 .data_in(data_in),.key_in(key_in),.data_out(data_out),.valid_out(valid_out),.done(done));
always #5 clk=~clk;
reg [127:0] pt[0:63],ky[0:63],expected[0:63];
integer errors=0,samples=0,sent=0,received=0,cycles=0,i;
integer last_received_cycle=-1;
always @(posedge clk) begin
 #1;
 cycles=cycles+1;
 if (rst) begin
   if (valid_out !== 0 || done !== 0) errors=errors+1;
 end else if (valid_out === 1) begin
   samples=samples+1;
   if (received>=sent || received>=64) errors=errors+1;
   else if (data_out !== expected[received] || done !== 1) errors=errors+1;
   // 前32个输入连续发送，流水线填满后必须每拍输出。
   if (received>0 && received<32 && cycles != last_received_cycle+1) errors=errors+1;
   last_received_cycle=cycles;
   received=received+1;
 end else if (valid_out !== 0) errors=errors+1;
end
initial begin
INIT
 repeat(3) @(negedge clk);
 rst=0;
 for(i=0;i<64;i=i+1) begin
   @(negedge clk);
   data_in=pt[i];key_in=ky[i];start=1;valid_in=1;sent=sent+1;
   if(i>=32 && i%3==0) begin @(negedge clk);start=0;valid_in=0; end
 end
 @(negedge clk);start=0;valid_in=0;
 repeat(100) @(negedge clk);
 if(received!=64) errors=errors+1;
 rst=1;
 repeat(3) @(negedge clk);
 $display("Mismatches: %0d in %0d samples",errors,samples);
 $finish;
end
initial begin #100000; $display("TIMEOUT"); $finish; end
endmodule
'''.replace('INIT',init)
    return source,tb


def gemm_fixture(base):
    spec=(base/'design-specs.txt').read_text()
    header=re.search(r'module systolic_matrix_mult\s*\(.*?\);',spec,re.S)[0].replace('systolic_matrix_mult','TopModule')
    source='''// 本地独立参考：16个有符号乘加PE，依据公开规格。
module pe(input [31:0] north_in,west_in,input clk,rst,
 output reg [31:0] south_out,east_out, output reg [63:0] result);
wire signed [63:0] product=$signed(north_in)*$signed(west_in);
always @(posedge clk) begin
 if(rst) begin south_out<=0;east_out<=0;result<=0;end
 else begin south_out<=north_in;east_out<=west_in;result<=result+product;end
end
endmodule
'''+header+'''
wire [31:0] east[0:15],south[0:15];
reg [4:0] count;
always @(posedge clk) begin
 if(rst) begin count<=0;done<=0;end
 else if(count<12) begin count<=count+1; if(count==11) done<=1;end
end
'''
    for r in range(4):
        for c in range(4):
            i=r*4+c
            west=f'a_west{r}' if c==0 else f'east[{i-1}]'
            north=f'b_north{c}' if r==0 else f'south[{i-4}]'
            source+=f'pe p{i}(.clk(clk),.rst(rst),.west_in({west}),.north_in({north}),.east_out(east[{i}]),.south_out(south[{i}]),.result(result{i}));\n'
    source+='endmodule\n'
    rng=random.Random(43240)
    identity=[int(i//4==i%4) for i in range(16)]
    matrices=[(list(range(1,17)),list(range(1,17))), (list(range(16)),identity),
              ([0]*16,identity), ([0x7fffffff if i%2 else -0x80000000 for i in range(16)],identity)]
    matrices += [([rng.randint(-1000,1000) for _ in range(16)], [rng.randint(-1000,1000) for _ in range(16)]) for _ in range(4)]
    init=[]
    for t,(a,b) in enumerate(matrices):
        for i in range(16):
            expected=sum(a[(i//4)*4+k]*b[k*4+i%4] for k in range(4)) & ((1<<64)-1)
            init.append(f"aa[{t*16+i}]=32'h{a[i]&0xffffffff:08x}; bb[{t*16+i}]=32'h{b[i]&0xffffffff:08x}; gold[{t*16+i}]=64'h{expected:016x};")
    ports=','.join([f'.a_west{i}(aw[{i}]),.b_north{i}(bn[{i}])' for i in range(4)]+[f'.result{i}(result[{i}])' for i in range(16)])
    tb='''`timescale 1ns/1ps
module tb;
reg clk=0,rst=1;
reg [31:0] aw[0:3],bn[0:3];
wire [63:0] result[0:15];
wire done;
TopModule dut(.clk(clk),.rst(rst),.done(done),PORTS);
always #5 clk=~clk;
reg [31:0] aa[0:127],bb[0:127];
reg [63:0] gold[0:127];
integer errors=0,samples=0,t,k,r,tl,waited;
initial begin
INIT
 for(r=0;r<4;r=r+1) begin aw[r]=0;bn[r]=0;end
 for(t=0;t<8;t=t+1) begin
   @(negedge clk);rst=1;
   repeat(3) @(negedge clk);
   if(done!==0) errors=errors+1;
   rst=0;
   for(tl=0;tl<=6;tl=tl+1) begin
     for(r=0;r<4;r=r+1) begin
       aw[r]=(tl>=r && tl<r+4)?aa[t*16+r*4+tl-r]:0;
       bn[r]=(tl>=r && tl<r+4)?bb[t*16+(tl-r)*4+r]:0;
     end
     @(posedge clk);#1;
     if(done!==0) errors=errors+1;
     @(negedge clk);
   end
   for(r=0;r<4;r=r+1) begin aw[r]=0;bn[r]=0;end
   waited=0;
   while(done!==1 && waited<30) begin @(posedge clk);#1;waited=waited+1;end
   if(done!==1) errors=errors+1;
   for(k=0;k<16;k=k+1) begin
     samples=samples+1;
     if(result[k]!==gold[t*16+k]) errors=errors+1;
   end
   @(posedge clk);#1;
   for(k=0;k<16;k=k+1) if(result[k]!==gold[t*16+k]) errors=errors+1;
 end
 $display("Mismatches: %0d in %0d samples",errors,samples);$finish;
end
initial begin #100000;$display("TIMEOUT");$finish;end
endmodule
'''.replace('PORTS',ports).replace('INIT','\n'.join(init))
    return source,tb


def convert_archxbench(base, out, helpers):
    save_task, source_record, rename, DATA = helpers
    records=[]
    adapters=DATA/'adapters/archxbench'
    for level,name,top in [('level-3','newton_raphson_sqrt','sqrt_newton_raphson_fixedpoint'),
                            ('level-5','systolic_gemm','systolic_matrix_mult'),
                            ('level-6','aes_encryption','aes128_pipeline')]:
        folder=base/level/name
        ps,ds,tp=[folder/f for f in ['problem-description.txt','design-specs.txt','tb.v']]
        prompt=ps.read_text(encoding='utf-8-sig')+'\n\n'+ds.read_text()
        prompt=re.sub(r'\b'+top+r'\b','TopModule',prompt)
        prompt='Implement the module named TopModule with the specification below.\n\n'+prompt
        files=[ps,ds,tp]
        if name=='newton_raphson_sqrt':
            source=(adapters/'sqrt.sv').read_text()
            tb=rename(tp.read_text(),{top:'TopModule'})
            tb=re.sub(r'\$(?:dumpfile|dumpvars)\([^;]*\);','',tb)
            tb=tb.replace('$display("Passed: %0d  Failed: %0d", pass_count, fail_count);',
                          '$display("Mismatches: %0d in %0d samples", fail_count, pass_count+fail_count);')
            notes=['本地独立参考实现；测试保留上游50组输入、浮点数学对照和原容差']
        elif name=='systolic_gemm':
            source,tb=gemm_fixture(folder)
            # 参考和候选的PE必须分别命名。
            source=rename(source,{'pe':'solution_pe'})
            notes=['本地独立参考实现；本地替换文件式测试台',
                   'Python整数矩阵乘法生成8组测试，含上游两组、零、单位阵、有符号边界和固定随机输入',
                   '检查复位、完成信号、16路结果和结果稳定性；不等同上游原始分数']
        else:
            source,tb=aes_fixture(folder,adapters)
            files.append(folder/'scripts/aes128.py')
            notes=['本地独立参考实现，只验默认 PIPELINED=1、UNROLL=1、INLINE_KEY_EXP=1',
                   '本地替换文件式测试台；上游Python AES模型生成64组嵌入向量，含标准已知答案、边界和固定种子随机输入',
                   '检查逐拍吞吐、输入空拍、密钥逐块变化、复位及输出顺序；不等同上游原始分数']
            prompt+='\n\nEvaluation configuration: PIPELINED=1, UNROLL=1, INLINE_KEY_EXP=1, mode=0.\n'
        prov=source_record('archxbench',files,base)
        prov['variant']='local_reference_adapter'
        records.append(save_task(out,'archxbench_'+level.replace('-','_')+'_'+name,prompt,
                                 rename(source,{'TopModule':'RefModule','solution_pe':'reference_pe'}),tb,source,prov,notes))
    return records
