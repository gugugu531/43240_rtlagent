`timescale 1ns/1ps
module tb();
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


  parameter DATA_WIDTH = 64;
  parameter STG_WIDTH = 16;

  reg CLK;
  reg RST;
  reg i_en;
  wire o_en;
  reg [DATA_WIDTH-1:0] PLUS_A;
  reg [DATA_WIDTH-1:0] PLUS_B;
  wire [DATA_WIDTH:0] SUM_OUT;
  wire [DATA_WIDTH:0] sum_out_golden;
  reg [DATA_WIDTH:0] sum_out_golden_ff1;
  reg [DATA_WIDTH:0] sum_out_golden_ff2;
  reg [DATA_WIDTH:0] sum_out_golden_ff3;
  reg [DATA_WIDTH:0] sum_out_golden_ff4;

  assign {sum_out_golden} = PLUS_A + PLUS_B;

  always #2 CLK = ~CLK;

  integer error = 0;
  initial begin
    CLK = 0;
    repeat (100) begin
      RST = 0;
      i_en = 0;
      #8 RST = 1;
      i_en = 1'b1;
      PLUS_A = $random * $random;
      PLUS_B = $random * $random;
      while(o_en==0) begin
        @(negedge CLK);
      end
        error = ((PLUS_A + PLUS_B) == SUM_OUT && o_en ==1 ) ? error : error + 1;
      @(negedge CLK);
    end

    if (error == 0) begin
      begin $display("=========== Your Design Passed ==========="); benchmark_done(1); end
    end
    else begin
      begin $display("=========== Test completed with %d / 100 failures ===========", error); benchmark_done(0); end
    end

    $finish;
  end

  always @(posedge CLK, negedge RST) begin
    if (!RST) begin
      sum_out_golden_ff1 <= 'd0;
      sum_out_golden_ff2 <= 'd0;
      sum_out_golden_ff3 <= 'd0;
      sum_out_golden_ff4 <= 'd0;
    end
    else begin
      sum_out_golden_ff1 <= sum_out_golden;
      sum_out_golden_ff2 <= sum_out_golden_ff1;
      sum_out_golden_ff3 <= sum_out_golden_ff2;
      sum_out_golden_ff4 <= sum_out_golden_ff3;
    end
  end

  TopModule #(
    .DATA_WIDTH(DATA_WIDTH),
    .STG_WIDTH(STG_WIDTH)
  )
  u_pip_add64 (
    .clk (CLK),
    .rst_n (RST),
    .i_en (i_en),
    .adda (PLUS_A),
    .addb (PLUS_B),
    .result (SUM_OUT),
    .o_en (o_en)
  );

endmodule
