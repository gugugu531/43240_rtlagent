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

reg clk_tb;
reg rst_tb;
wire [3:0] out_tb;

TopModule DUT(
    .out(out_tb),
    .clk(clk_tb),
    .rst(rst_tb)
);

initial
begin
    clk_tb = 0;
    rst_tb = 1;
    #15;
    
    rst_tb = 0;
    #200;
    // $display("Failed: out=%b (expected 1101)", out_tb);
    if (out_tb == 4'b1101) begin
      begin $display("=========== Your Design Passed ==========="); benchmark_done(1); end
    end
    else begin
      begin $display("=========== Failed ==========="); benchmark_done(0); end
    end
    $finish;
end

always
begin
    #5;
    clk_tb = ~ clk_tb;
end


endmodule
