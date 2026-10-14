`timescale 1ns/1ns
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

  reg clk;
  reg d;
  wire [7:0] q;

  // Instantiate the DUT (Design Under Test)
  TopModule dut (
    .clk(clk),
    .d(d),
    .q(q)
  );

  // Generate clock
  always #5 clk = ~clk;

  initial begin
    // Initialize inputs
    clk = 0;
    d = 0;
    #20;
    d = 1;
    #10;
    d = 0;
    #10;
    d = 1;
    #10;
    d = 0;
    #10;
    d = 1;
    #10;
    d = 1;
    #10;
    d = 1;
    #10;
    
    // Check the output
    if(q==8'b11101010) begin
      begin $display("===========Your Design Passed==========="); benchmark_done(1); end
    end
    else begin
      begin $display("===========Failed==========="); benchmark_done(0); end
    end
    // Finish simulation
    $finish;
  end
endmodule
