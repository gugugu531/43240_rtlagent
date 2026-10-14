`timescale 1ns/1ps
module tb ();
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


reg  clk,rst;

wire out1;
wire out2;
wire out3;

TopModule dut(.CLK_in(clk),.RST(rst),.CLK_50(out1),.CLK_10(out2),.CLK_1(out3));

initial begin
	clk = 0;
	forever #5 clk = ~clk;
end

integer error=0;

initial begin 
	#10;
	rst = 1;
	#35;
	rst = 0;
	// 45, clk: 1, clk50: 0, rclk10: 0, clk1: 0
	error = (out1 != 0 || out2 != 0 || out3 !=0 ) ? error+1 : error;
	// 55, clk: 1, clk50: 1, rclk10: 0, clk1: 0
	#10;
	error = (out1 != 1 || out2 != 0 || out3 !=0 ) ? error+1 : error;
	// 95, clk50: 0, rclk10: 1, clk1: 0
	#40;
	error = (out1 != 1 || out2 != 1 || out3 !=0 ) ? error+1 : error;
	// 225, clk: 1, clk50: 0, rclk10: 1, clk1: 0
	#130;
	error = (out1 != 0 || out2 != 1 || out3 !=0 ) ? error+1 : error;
	// 625, clk: 1, clk50: 0, rclk10: 1, clk1: 1
	#400;
	error = (out1 != 0 || out2 != 1 || out3 !=1 ) ? error+1 : error;
	// 1035, clk: 1, clk50: 1, rclk10: 1, clk1: 1
	#410;
	error = (out1 != 1 || out2 != 1 || out3 !=1 ) ? error+1 : error;
	if (error == 0) begin
            begin $display("===========Your Design Passed==========="); benchmark_done(1); end
        end
        else begin
        begin $display("===========Error===========", error); benchmark_done(0); end
        end
	$finish;
end

// initial begin 
// 	repeat(500) begin
// 		#5
// 		$display("Time: %t, clk: %b, clk50: %b, rclk10: %b, clk1: %b", $time, clk, out1, out2, out3);
// 	end
// end

endmodule
