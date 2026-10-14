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


  reg [7:0] A;          // Input A (8 bits)
  reg [7:0] B;          // Input B (8 bits)
  wire [15:0] product;  // Product result (16 bits)
  integer i;            // Loop variable
  integer error = 0;    // Error count for failed tests

  TopModule uut (
    .A(A),
    .B(B),
    .product(product)
  );

  // Test cases
  initial begin

    for (i = 0; i < 100; i = i + 1) begin
      // Generate random 8-bit inputs
      A = $random;
      B = $random;

      // Wait for the operation to complete
      #10;

    //   $display("A = %d, B = %d, Expected Product = %d", A, B, A * B);

      // Check the result of the multiplication
      if (product !== A * B) begin
        error = error + 1;
        begin tb.benchmark_error = 1; $display("Test failed: A = %d, B = %d, Expected Product = %d, Got = %d", A, B, A * B, product); end
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
