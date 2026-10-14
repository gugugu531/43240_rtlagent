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


  reg [63:0] A;          // Input A (64 bits)
  reg [63:0] B;          // Input B (64 bits)
  wire [63:0] result;    // Subtraction result (64 bits)
  wire overflow;         // Overflow signal
  integer i;             // Loop variable
  integer error = 0;     // Error count for failed tests

  // Instantiate the verified_sub_64bit module
  TopModule uut (
    .A(A),
    .B(B),
    .result(result),
    .overflow(overflow)
  );

  // Randomize inputs and check output
  initial begin
    for (i = 0; i < 100; i = i + 1) begin
        // Generate random 64-bit inputs
        A = $random;
        B = $random;

        // Wait for the operation to complete
        #10;

        // Calculate expected result using system task
        // $monitor("A = %d, B = %d, Expected Result = %d, Overflow = %b", A, B, A - B, overflow);

        // Check the result of the subtraction
        if (result !== (A - B) || (A - B < 0 && overflow !== 1)) begin
            error = error + 1;
            begin tb.benchmark_error = 1; $display("Test failed: A = %d, B = %d, Expected Result = %d, Got = %d, Overflow = %b", A, B, A - B, result, overflow); end
        end
    end

    // Final test result summary
    if (error == 0) begin
      begin $display("=========== Your Design Passed ==========="); benchmark_done(1); end
    end
    else begin
      begin $display("=========== Test completed with %d /100 failures ===========", error); benchmark_done(0); end
    end

    $finish;
  end

endmodule
