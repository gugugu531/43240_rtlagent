`timescale 1ns/1ns

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


    // Parameters
    parameter CLK_PERIOD = 10; // Clock period in simulation time units
    
    // Inputs
    reg clk;
    reg rst_n;
    
    // Outputs
    wire [63:0] Q;

    // Instantiate the module
    TopModule uut (
        .clk(clk),
        .rst_n(rst_n),
        .Q(Q)
    );
    
    // Clock generation
    always #((CLK_PERIOD)/2) clk = ~clk;
    
    integer error=0;
    // Initial block for stimulus generation
    initial begin
        // Initialize inputs
        clk = 0;
        rst_n = 1;
        
        // Wait for a few clock cycles
        #((CLK_PERIOD) * 2);
        
        // Release reset
        rst_n = 0;
        #((CLK_PERIOD) * 2);
        rst_n = 1;
        
        // Simulate for a number of clock cycles
        #((CLK_PERIOD) * 20);
        error = (Q ==64'b 1111111111111111111100000000000000000000000000000000000000000000)? error : error+1;
        #((CLK_PERIOD) * 44);
        error = (Q ==64'b 1111111111111111111111111111111111111111111111111111111111111111)? error : error+1;
        #((CLK_PERIOD) * 1);
        error = (Q ==64'b 0111111111111111111111111111111111111111111111111111111111111111)? error : error+1;
        #((CLK_PERIOD) * 62);
        error = (Q ==64'b 0000000000000000000000000000000000000000000000000000000000000001)? error : error+1;

        if (error == 0) begin
            begin $display("===========Your Design Passed==========="); benchmark_done(1); end
        end
        else begin
        begin $display("===========Error==========="); benchmark_done(0); end
        end
        // $display("Q = %b", Q); 
        
        // Finish simulation
        $finish;
    end

endmodule
