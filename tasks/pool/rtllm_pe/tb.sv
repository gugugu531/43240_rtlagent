`timescale 1ns / 1ps

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


    reg clk;
    reg rst;
    reg [31:0] a,b;
    wire [31:0] c;
    
    TopModule dut(clk,rst,a,b,c);


    initial begin

    a=0;
    b=0;
    clk=0;
    rst=1;
    #5;
    clk=1;
    #5;
    clk=0;
    rst=0;
    #5;

    a=1;
    b=1;
    #5;
    clk=1;
    #5;
    clk=0;

    a=2;
    b=2;
    #5;
    clk=1;
    #5;
    clk=0;

    a=3;
    b=3;
    #5;
    clk=1;
    #5;
    clk=0;

    //$display("%h", c);

	if(c==32'h0000000e)
	begin
		begin $display("===========Your Design Passed==========="); benchmark_done(1); end
        end
	else
	begin
		begin $display("===========Error==========="); benchmark_done(0); end
	end
    end
endmodule
