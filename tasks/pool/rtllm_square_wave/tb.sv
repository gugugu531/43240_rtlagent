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


    reg clk_tb = 0;        
    reg [8:0] freq_tb = 8'b0000100; 
    wire wave_out_tb;       
    integer ones_count = 0;  // Counter for consecutive ones
    integer error = 0;       // Error flag

    TopModule square_wave_inst (
        .clk(clk_tb),
        .freq(freq_tb),
        .wave_out(wave_out_tb)
    );

    initial begin
        // Monitor output
        // $monitor("Time: %0t | Clock: %b | Frequency: %d | Square Wave Output: %b | Error: %d", $time, clk_tb, freq_tb, wave_out_tb, error);

        // Simulate for a certain time
        repeat (200) begin
            if (wave_out_tb == 1) begin
                ones_count = ones_count + 1;
                if (ones_count > 8) begin
                    begin tb.benchmark_error = 1; $display("Error: More than 8 consecutive ones detected at time %0t", $time); end
                    error = 1;  // Set error flag
                    $finish;    // Stop the simulation
                end
            end else begin
                ones_count = 0;
            end
            #5; // Time delay between clock cycles
        end
        if (error == 0) begin
            begin $display("=========== Your Design Passed ==========="); benchmark_done(1); end
        end
        $finish;  // Finish the simulation
    end

    always #5 clk_tb = ~clk_tb;

endmodule
