`timescale 1ns/1ps
module tb;
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


  reg clk, rst_n, valid_count;
  wire [3:0] out;

  TopModule dut (
    .rst_n(rst_n),
    .clk(clk),
    .valid_count(valid_count),
    .out(out)
  );


  always #5 clk = ~clk;
  integer i = 0;
  integer error = 0;
  initial begin
    clk = 0;
    rst_n = 0;
    valid_count = 0;

    #20 rst_n = 1;
    // testcase1: validation of valid_count
    repeat(15) begin	
      error = (out == 0) ?error:error+1;
      #10;
    end
    // testcase2: counter
    #100 valid_count = 1;
    repeat(11) begin	
      error = (out == i) ?error:error+1;
      i = i+1;
      #10;
    end
    // testcase3: the count is paused if valid_count is invalid
    valid_count = 0;
    repeat(5) begin	
      error = (out == 11) ?error:error+1;
      #10;
    end

    if (error == 0) begin
              begin $display("===========Your Design Passed==========="); benchmark_done(1); end
          end
          else begin
          begin $display("===========Failed===========", error); benchmark_done(0); end
          end
    $finish;
  end


endmodule
