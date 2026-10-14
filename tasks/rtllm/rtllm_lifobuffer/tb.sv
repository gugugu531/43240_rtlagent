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


// Inputs
reg [3:0] dataIn;
reg RW;
reg EN;
reg Rst;
reg Clk;

// Outputs
wire [3:0] dataOut;
wire EMPTY;
wire FULL;

// Instantiate the Unit Under Test (UUT)
TopModule uut (
    .dataIn(dataIn),
    .dataOut(dataOut),
    .RW(RW),
    .EN(EN),
    .Rst(Rst),
    .EMPTY(EMPTY),
    .FULL(FULL),
    .Clk(Clk)
);
integer error = 0;
initial begin
    // Initialize Inputs
    dataIn = 4'h0;
    RW = 1'b0;
    EN = 1'b0;
    Rst = 1'b1;
    Clk = 1'b0;

    // Wait 100 ns for global reset to finish
    #100;

    // Add stimulus here
    EN = 1'b1;
    Rst = 1'b1;
    #40;
    Rst = 1'b0;
    RW = 1'b0;
    dataIn = 4'h0;
    #20;
    dataIn = 4'h2;
    #20;
    dataIn = 4'h4;
    #20;
    dataIn = 4'h6;
    #20;
    RW = 1'b1;
    #5;
    // $display(FULL,EMPTY);
    error = (FULL && !EMPTY) ? error : error+1;
    #20;
    // $display(dataOut);
    error = (dataOut==6) ? error : error+1;
    #20;
    // $display(dataOut);
    error = (dataOut==4) ? error : error+1;
    if (error == 0) begin
            begin $display("=========== Your Design Passed ==========="); benchmark_done(1); end
            end
        else begin
            begin $display("=========== Test completed with %d/20 failures ===========", error); benchmark_done(0); end
    end
    $finish;
end

always #10 Clk = ~Clk;

endmodule
