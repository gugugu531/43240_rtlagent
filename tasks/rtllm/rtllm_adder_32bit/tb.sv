`timescale  1ns/1ns
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

  
  reg [31:0] A;
  reg [31:0] B;
  wire [31:0] S;
  wire C32;
  
  integer i; 
  integer error = 0; 
  reg [33:0] expected_sum; 
  
  // Instantiate the module
  TopModule uut (
    .A(A), 
    .B(B), 
    .S(S), 
    .C32(C32)
  );
  
  // Randomize inputs and check output
  initial begin
    for (i = 0; i < 100; i = i + 1) begin
      A = $random;
      B = $random;
      #10; 
      // Calculate expected sum and carry out
      expected_sum = A + B;
      error = (S !== expected_sum[31:0] || C32 !== expected_sum[32]) ? error+1 : error; 
    end
    if (error == 0) begin
            begin $display("===========Your Design Passed==========="); benchmark_done(1); end
    end
    else begin
    begin $display("===========Test completed with %d /100 failures===========", error); benchmark_done(0); end
    end
  end

endmodule
