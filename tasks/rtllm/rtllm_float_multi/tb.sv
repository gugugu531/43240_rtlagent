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


reg [31:0] a, b;
wire [31:0] z;
reg clk, rst;

TopModule uut(clk , rst, a, b, z);
integer error = 0;
initial begin
	clk <= 0;
	rst <= 1;
	repeat(17000)
		#5 clk <= ~clk;
end

initial #13 rst <= 0;

initial begin
// $monitor("a=%b, b=%b, z=%b", a,b,z);
	#3
	repeat(2) begin
		#80
		a = 32'b00111110100110011001100110011010;
		b = 32'b00111110100110011001100110011010;
	end
	
	#80
    error = (z==32'b00111101101110000101000111101100) ? error:error+1;
    if (error == 0) begin
            begin $display("=========== Your Design Passed ==========="); benchmark_done(1); end
            end
    else begin
        begin $display("=========== Test completed with %d/20 failures ===========", error); benchmark_done(0); end
    end
    $finish;
end


endmodule
