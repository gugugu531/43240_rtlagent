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

  reg [7:0] in;
  reg [2:0] ctrl;
  wire [7:0] out; 
  
TopModule uut(.in(in), .ctrl(ctrl), .out(out));

integer error = 0;

initial 
    begin
        in= 8'd0;  ctrl=3'd0; //no shift
        #10 in=8'd128; ctrl= 3'd4; //shift 4 bit
        #10 error = (out==8)?error : error+1;
        #10 in=8'd128; ctrl= 3'd2; //shift 2 bit
        #10 error = (out==32)?error : error+1;
        #10 in=8'd128; ctrl= 3'd1; //shift by 1 bit
        #10 error = (out==64)?error : error+1;
        #10 in=8'd255; ctrl= 3'd7; //shift by 7bit
        #10 error = (out==1)?error : error+1;
        #10 in=8'b00000001; ctrl= 3'd1; //logical right shift, no rotation
        #10 error = (out==0)?error : error+1;
    // end
    // initial begin
    //     $monitor("Input=%d, Control=%d, Output=%d",in,ctrl,out);
    // end
        if (error == 0) begin
            begin $display("=========== Your Design Passed ==========="); benchmark_done(1); end
            end
        else begin
            begin $display("=========== Test completed with %d failures ===========", error); benchmark_done(0); end
        end
        $finish;
    end
endmodule
