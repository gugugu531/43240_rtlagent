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


reg clk;
reg rst;
reg [1:0] fetch;
reg [7:0] data;

wire [2:0] ins;
wire [4:0] ad1;
wire [7:0] ad2;

TopModule uut (
    .clk(clk),
    .rst(rst),
    .fetch(fetch),
    .data(data),
    .ins(ins),
    .ad1(ad1),
    .ad2(ad2)
);

integer error;
integer expected_ins;
integer expected_ad1;
integer expected_ad2;

initial begin
    // Initialize Inputs
    clk = 0;
    rst = 0;
    fetch = 2'b00;
    data = 8'h00;
    error = 0;

    // Wait 100 ns for initialization
    #100;

    // De-assert reset
    rst = 1;
    #10;

    // Perform fetch operation 1 from register
    fetch = 2'b01;
    #5;
    data = 8'b01011100;
    expected_ins = 3'b010;
    expected_ad1 = 5'b11100;
    expected_ad2 = 8'b00;
    #20;

    // Check the values
    if (ins !== expected_ins) begin
        error = error + 1; 
        begin tb.benchmark_error = 1; $display("Failed at fetch operation 1: clk=%d, ins=%b (expected %d)", clk, ins, expected_ins); end
    end

    if (ad1 !== expected_ad1) begin
        error = error + 1; 
        begin tb.benchmark_error = 1; $display("Failed at fetch operation 1: clk=%d, ad1=%b (expected %d)", clk, ad1, expected_ad1); end
    end

    if (ad2 !== expected_ad2) begin
        error = error + 1; 
        begin tb.benchmark_error = 1; $display("Failed at fetch operation 1: clk=%d, ad2=%b (expected %d)", clk, ad2, expected_ad2); end
    end

    // Additional test cases can be added here

    // Finish simulation and display total errors
    if (error == 0) begin
            begin $display("=========== Your Design Passed ==========="); benchmark_done(1); end
            end
    else begin
        begin $display("=========== Test completed with %d failures ===========", error); benchmark_done(0); end
    end
    $finish;
end

always #5 clk = ~clk;

endmodule
