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


    reg clk_tb; // Clock signal from the testbench
    reg res = 1'b0;
    integer error = 0;
    // Instantiate the clkgenerator module
    TopModule clkgenerator_inst (
        .clk(clk_tb)
    );

    initial begin
        // Monitor the clock signal
        // $monitor("Time=%0t, clk=%b", $time, clk_tb);

        // Simulate for a certain number of clock cycles
        repeat (20) begin // Simulate 20 clock cycles
            #5; // Time delay between clock cycles
            error = (res == clk_tb) ? error :error+1;
            res = res + 1;
            // $display(clk_tb);
        end
        if (error == 0) begin
        begin $display("=========== Your Design Passed ==========="); benchmark_done(1); end
        end
        else begin
        begin $display("=========== Test completed with %d failures ===========", error); benchmark_done(0); end
        end
        // Finish simulation
        $finish;
    end

endmodule
