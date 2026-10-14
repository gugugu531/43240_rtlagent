`timescale 1ns/1ns

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


reg clk,rst;
reg IN;
wire MATCH;

TopModule DUT(.CLK(clk),.RST(rst),.IN(IN),.MATCH(MATCH));

initial begin
	clk=0;
	forever #5 clk=~clk;
end

integer error = 0;
initial begin
	#10;
	rst =1;
	#28;
	rst = 0;
	IN = 0;
	#10 IN=0;
        // $display("%b, %b", MATCH, DUT.ST_cr);//0
        error = (MATCH==0)? error:error+1;
        #10 IN=0;
        // $display("%b, %b", MATCH, DUT.ST_cr);//00
        error = (MATCH==0)? error:error+1;
        #10 IN=1;
        // $display("%b, %b", MATCH, DUT.ST_cr);//001
        error = (MATCH==0)? error:error+1;
        #10 IN=1;  
        // $display("%b, %b", MATCH, DUT.ST_cr);//0011
        error = (MATCH==0)? error:error+1;
        #10 IN=0;
        // $display("%b, %b", MATCH, DUT.ST_cr);//00110
        error = (MATCH==0)? error:error+1;
        #10 IN=0;
        // $display("%b, %b", MATCH, DUT.ST_cr);//001100
        error = (MATCH==0)? error:error+1;
        #10 IN=1;
        // $display("%b, %b", MATCH, DUT.ST_cr);//0011001
        error = (MATCH==0)? error:error+1;
        #10 IN=1;
        // $display("%b, %b", MATCH, DUT.ST_cr);//00110011
        error = (MATCH==1)? error:error+1;
        #10 IN=0;
        // $display("%b, %b", MATCH, DUT.ST_cr);//001100110
        error = (MATCH==0)? error:error+1;
        #10 IN=0;
        // $display("%b, %b", MATCH, DUT.ST_cr);//0011001100
        error = (MATCH==0)? error:error+1;
        #10 IN=1;
        // $display("%b, %b", MATCH, DUT.ST_cr);//00110011001
        error = (MATCH==0)? error:error+1;
        #10 IN=1;
        // $display("%b, %b", MATCH, DUT.ST_cr);//001100110011
        error = (MATCH==1)? error:error+1;
        if(error==0)begin
                begin $display("===========Your Design Passed==========="); benchmark_done(1); end
        end
        else begin
                begin $display("===========Error==========="); benchmark_done(0); end
        end
	$finish;
end
endmodule
