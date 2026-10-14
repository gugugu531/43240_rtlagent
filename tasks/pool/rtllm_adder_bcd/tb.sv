`timescale 1ns / 1ps

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


  reg [3:0] A;    // First BCD input (4 bits)
  reg [3:0] B;    // Second BCD input (4 bits)
  reg Cin;        // Carry-in input (1 bit)
  wire [3:0] Sum; // BCD sum output (4 bits)
  wire Cout;      // Carry-out output (1 bit)

  integer i;      
  integer error = 0; 
  reg [4:0] expected_sum; 


  TopModule uut (
    .A(A),
    .B(B),
    .Cin(Cin),
    .Sum(Sum),
    .Cout(Cout)
  );

  initial begin
    for (i = 0; i < 100; i = i + 1) begin
        A = $random % 10; 
        B = $random % 10;
        Cin = $random % 2;
        if (A > 9) A = A % 10;
        if (B > 9) B = B % 10;
        // Wait for the operation to complete
        #10;

        expected_sum = A + B + Cin;

        // Adjust for BCD overflow (sum greater than 9)
        if (expected_sum > 9) begin
            expected_sum = expected_sum + 6;  // Correct the sum for BCD
        end

        // Check the result of the BCD adder
        if ({Cout, Sum} !== expected_sum) begin
            error = error + 1;
            begin tb.benchmark_error = 1; $display("Test failed: A = %d, B = %d, Cin = %d | Expected = %d, Got = %d, Cout = %d", 
                     A, B, Cin, expected_sum, Sum, Cout); end
        end
    end
    
    if (error == 0) begin
      begin $display("=========== Your Design Passed ==========="); benchmark_done(1); end
    end
    else begin
      begin $display("=========== Test completed with %d /100 failures ===========", error); benchmark_done(0); end
    end

    $finish;
  end

endmodule
