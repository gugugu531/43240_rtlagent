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


    reg clk, rst_n, data_in;
    wire sequence_detected;

    TopModule dut (
        .clk(clk),
        .rst_n(rst_n),
        .data_in(data_in),
        .sequence_detected(sequence_detected)
    );
    integer error = 0;  
    // Clock generation
    always #5 clk = ~clk;

    initial begin
        // Initialize signals
        clk = 0;
        rst_n = 0;
        data_in = 1;
        #2 rst_n = 1;


        // Sending 1001
        #6 data_in = 1;
        #10 data_in = 1;
        #10 data_in = 0;
        #10 data_in = 0;
        #10 data_in = 1;
        #10;data_in = 1; 
        if (!sequence_detected)
            error = error+1;
        #10;data_in = 1;
        #10 data_in = 0;
        if (sequence_detected)
            error = error+1;
        #10 data_in = 0;
        #10 data_in = 1;
        #10;
        if (!sequence_detected)
            error = error+1;
    if (error == 0) begin
      begin $display("=========== Your Design Passed ==========="); benchmark_done(1); end
    end
    else begin
      begin $display("=========== Test completed with %d /3 failures ===========", error); benchmark_done(0); end
    end           
        $finish;
    end

endmodule
