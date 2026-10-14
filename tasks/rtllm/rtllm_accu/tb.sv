`timescale  1ns / 1ps

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



parameter PERIOD  = 10;
reg   clk                                  = 0 ;
reg   rst_n                                = 0 ;
reg   [7:0]  data_in                       = 0 ;
reg   valid_in                             = 0 ;

wire  valid_out                              ;
wire  [9:0]  data_out                       ;


initial
begin
    forever #(PERIOD/2)  clk=~clk;
end

initial
begin
    #(PERIOD*2) rst_n  =  1;
end

TopModule  uut (
    .clk                     ( clk             ),
    .rst_n                   ( rst_n           ),
    .data_in                 ( data_in   [7:0] ),
    .valid_in                ( valid_in        ),

    .valid_out               ( valid_out       ),
    .data_out                ( data_out  [9:0] )
);

initial
begin
    #(PERIOD*1+0.01); 
    #(PERIOD)   data_in = 8'd1;valid_in = 1;
    #(PERIOD)   data_in = 8'd2;
    #(PERIOD)   data_in = 8'd3;
    #(PERIOD)   data_in = 8'd14;

    #(PERIOD)   data_in = 8'd5;
    #(PERIOD)   data_in = 8'd2;
    #(PERIOD)   data_in = 8'd103;
    #(PERIOD)   data_in = 8'd4;

    #(PERIOD)   data_in = 8'd5;
    #(PERIOD)   data_in = 8'd6;
    #(PERIOD)   data_in = 8'd3;
    #(PERIOD)   data_in = 8'd54;
    #(PERIOD*2);
    $finish;
end

reg [9:0] result [0:2];
initial begin
    result[0] = 9'd20;
    result[1] = 9'd114;
    result[2] = 9'd68;
end

integer i;
integer casenum = 0;
integer error = 0;

initial
begin
    for (i = 0; i < 15; i = i + 1) begin
        #((PERIOD) * 1);         
        if (valid_out) begin
            error = (data_out == result[casenum]) ? error : error + 1;
            casenum = casenum + 1;
        end        
    end
    if(error==0 && casenum==3)
	begin
		begin $display("===========Your Design Passed==========="); benchmark_done(1); end
        end
	else
	begin
		begin $display("===========Error==========="); benchmark_done(0); end
	end
    $finish;
end


endmodule
