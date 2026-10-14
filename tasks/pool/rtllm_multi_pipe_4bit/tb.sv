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
  reg rst_n;
  reg [3:0] mul_a;
  reg [3:0] mul_b;
  wire [7:0] mul_out;
  wire signed [7:0] perfect = mul_a*mul_b;
  // Instantiate the DUT (Design Under Test)
  TopModule #(.size(4)) dut (
    .clk(clk),
    .rst_n(rst_n),
    .mul_a(mul_a),
    .mul_b(mul_b),
    .mul_out(mul_out)
  );

  // Generate clock
  always #5 clk = ~clk;

  integer fail_count =0;
  integer i=0;
  initial begin
    // Initialize inputs
    clk = 0;
    rst_n = 0;
    mul_a = 4'b0;
    mul_b = 4'b0;

    // Wait for a few clock cycles for reset to settle
    #10;

    // Apply reset
    rst_n = 1;
  
    // Perform test case
    for (i = 0; i < 100; i = i + 1) begin
      mul_a =  $random;
      mul_b =  $random;
      #10;
      // without pipeline
      fail_count = (perfect == mul_out)? fail_count+1:fail_count;
      #20;
      // $display("%d, %d, %d, %d", mul_a, mul_b, perfect, mul_out);
      fail_count = (perfect == mul_out)? fail_count:fail_count+1;
    end

    if (fail_count == 0) begin
        begin $display("===========Your Design Passed==========="); benchmark_done(1); end
    end
    else begin
    begin $display("===========Test completed with %d / 100 failures===========", fail_count); benchmark_done(0); end
    end
    $finish;
  end
endmodule
