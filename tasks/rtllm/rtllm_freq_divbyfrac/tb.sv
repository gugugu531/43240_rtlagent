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
    reg clk;
    reg rst_n;
    // Outputs
    wire clk_div;
 
    // Instantiate the Unit Under Test (UUT)
    TopModule uut (
        .clk(clk), 
        .rst_n(rst_n), 
        .clk_div(clk_div)
    );
    always #5 clk = ~clk;
    
    integer error = 0;
    integer expected_value = 1;
    integer i;
    initial begin
        // Initialize Inputs
        clk = 1;
        rst_n = 0;
        # 10 rst_n = 1;
        #120;

        $finish;
    end
    initial begin
        // $monitor("clk=%d, clk_div=%d",clk,clk_div);
        #15;
        for (i = 0; i < 20; i = i + 1) begin
            if (clk_div !== expected_value) begin
                error = error + 1; 
                begin tb.benchmark_error = 1; $display("Failed at%d: clk=%d, clk_div=%d (expected %d)", i,clk, clk_div, expected_value); end
            end

            if (i < 2) expected_value = 1; 
            else if (i < 6) expected_value = 0; 
            else if (i < 9) expected_value = 1; 
            else if (i < 13) expected_value = 0; 
            else if (i < 16) expected_value = 1; 
            else if (i < 20) expected_value = 0; 
            else expected_value = 1; // Last five pairs
            #5;
        end
        if (error == 0) begin
            begin $display("=========== Your Design Passed ==========="); benchmark_done(1); end
            end
        else begin
            begin $display("=========== Test completed with %d/20 failures ===========", error); benchmark_done(0); end
        end
    end
endmodule
