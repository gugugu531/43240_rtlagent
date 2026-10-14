// 本地独立编写；依据 ArchXBench AES-128 流水线公开规格。
// SBOX_CASES 由转换器按有限域运算生成，不读取 RTL 参考答案。
module TopModule #(parameter PIPELINED=1, UNROLL=1, INLINE_KEY_EXP=1)(
  input clk, rst, start, mode, input [127:0] data_in, key_in, input valid_in,
  output [127:0] data_out, output valid_out, done
);
  function automatic [7:0] sb(input [7:0] x);
    begin
      case (x)
// SBOX_CASES
      endcase
    end
  endfunction
  function automatic [7:0] xt(input [7:0] x);
    xt = {x[6:0],1'b0} ^ (x[7] ? 8'h1b : 8'h00);
  endfunction
  function automatic [7:0] rc(input integer round_index);
    reg [7:0] v;
    integer i;
    begin
      v=1;
      for (i=1;i<round_index;i=i+1) v=xt(v);
      rc=v;
    end
  endfunction
  function automatic [127:0] expand(input [127:0] k, input integer round_index);
    reg [31:0] w0,w1,w2,w3,t;
    begin
      t={sb(k[23:16]),sb(k[15:8]),sb(k[7:0]),sb(k[31:24])} ^ {rc(round_index),24'b0};
      w0=k[127:96]^t; w1=k[95:64]^w0;
      w2=k[63:32]^w1; w3=k[31:0]^w2;
      expand={w0,w1,w2,w3};
    end
  endfunction
  function automatic [127:0] aes_round(input [127:0] s, input integer last);
    reg [7:0] b[0:15];
    reg [7:0] a,c,d,e,total;
    integer row,col;
    begin
      for (col=0;col<4;col=col+1)
        for (row=0;row<4;row=row+1)
          b[col*4+row]=sb(s[127-(4*((col+row)%4)+row)*8 -: 8]);
      for (col=0;col<4;col=col+1) begin
        a=b[col*4]; c=b[col*4+1]; d=b[col*4+2]; e=b[col*4+3];
        total=a^c^d^e;
        if (!last) begin
          b[col*4]=a^total^xt(a^c);
          b[col*4+1]=c^total^xt(c^d);
          b[col*4+2]=d^total^xt(d^e);
          b[col*4+3]=e^total^xt(e^a);
        end
      end
      for (col=0;col<16;col=col+1) aes_round[127-col*8 -: 8]=b[col];
    end
  endfunction
  reg [127:0] state[0:10], keys[0:10];
  reg [10:0] valid;
  integer j;
  always @(posedge clk) begin
    if (rst) begin
      valid<=0;
      for (j=0;j<=10;j=j+1) begin state[j]<=0; keys[j]<=0; end
    end else begin
      valid[0]<=valid_in && start && !mode;
      state[0]<=data_in^key_in; keys[0]<=key_in;
      for (j=1;j<=10;j=j+1) begin
        valid[j]<=valid[j-1];
        keys[j]<=expand(keys[j-1],j);
        state[j]<=aes_round(state[j-1],j==10)^expand(keys[j-1],j);
      end
    end
  end
  assign data_out=state[10];
  assign valid_out=valid[10];
  assign done=valid_out;
endmodule
