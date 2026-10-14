// 本地独立编写的参考实现，依据 ArchXBench 的公开规格；不是上游提供的答案。
module TopModule #(
    parameter N=16, M=8, ITER_MAX=10
)(input clk, rst, start, input [N-1:0] X,
  output reg [N-1:0] sqrt_result, output reg ready);
  reg [N-1:0] operand, estimate;
  reg busy;
  integer iteration;
  wire [2*N-1:0] scaled = {{N{1'b0}}, operand} << M;
  wire [2*N:0] refined = ({1'b0, {{N{1'b0}}, estimate}} +
                                  (scaled / estimate)) >> 1;
  always @(posedge clk) begin
    if (rst) begin
      operand <= 0; estimate <= 0; busy <= 0;
      iteration <= 0; sqrt_result <= 0; ready <= 0;
    end else if (start && !busy) begin
      operand <= X; estimate <= X; iteration <= 0;
      if (X == 0) begin sqrt_result <= 0; ready <= 1; busy <= 0; end
      else begin ready <= 0; busy <= 1; end
    end else if (busy) begin
      estimate <= refined[N-1:0];
      iteration <= iteration + 1;
      if (iteration == ITER_MAX-1 || refined == estimate) begin
        sqrt_result <= refined[N-1:0]; ready <= 1; busy <= 0;
      end
    end
  end
endmodule
