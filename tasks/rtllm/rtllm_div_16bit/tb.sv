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


reg [15:0] A;
reg [7:0] B;
wire [15:0] result;
wire [15:0] odd;

integer i; 
integer error = 0; 
reg [15:0] expected_result;
reg [15:0] expected_odd;
initial begin
   for (i = 0; i < 100; i = i + 1) begin
      A = $urandom_range(1'b0, 16'b1111_1111_1111_1111);
      B = $urandom_range(1'b1, 8'b1111_1111);
      expected_result = A/B;
      expected_odd = A%B;
      #10; 
      error = (expected_odd != odd || expected_result != result) ? error+1 : error;
      // $display("A = %d, B = %d, Result = %d, odd = %d", A, B, result, odd);
   end
   
   if (error == 0) begin
            begin $display("===========Your Design Passed==========="); benchmark_done(1); end
    end
    else begin
    begin $display("===========Test completed with %d /100 failures===========", error); benchmark_done(0); end
    end
    
    $finish;
end

TopModule uut (.A(A), .B(B), .result(result), .odd(odd));

endmodule
