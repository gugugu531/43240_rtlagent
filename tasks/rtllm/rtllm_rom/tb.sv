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


    reg [7:0] addr_tb;          // Address input for the ROM
    wire [15:0] dout_tb;        // Data output from the ROM

    TopModule rom_inst (
        .addr(addr_tb),
        .dout(dout_tb)
    );

    integer error;

    initial begin
        // Initialize simulation
        $display("Starting ROM Testbench...");
        error = 0;

        // Test reading data from different memory locations
        addr_tb = 8'h00;  // Read from address 0
        #10;
        if (dout_tb !== 16'hA0A0) begin
            begin tb.benchmark_error = 1; $display("Error: Data read from address 0 is incorrect"); end
            error = error + 1;
        end

        addr_tb = 8'h01;  // Read from address 1
        #10;
        if (dout_tb !== 16'hB1B1) begin
            begin tb.benchmark_error = 1; $display("Error: Data read from address 1 is incorrect"); end
            error = error + 1;
        end

        addr_tb = 8'h02;  // Read from address 2
        #10;
        if (dout_tb !== 16'hC2C2) begin
            begin tb.benchmark_error = 1; $display("Error: Data read from address 2 is incorrect"); end
            error = error + 1;
        end

        addr_tb = 8'h03;  // Read from address 3
        #10;
        if (dout_tb !== 16'hD3D3) begin
            begin tb.benchmark_error = 1; $display("Error: Data read from address 3 is incorrect"); end
            error = error + 1;
        end

        // Add more test cases here if needed

        // Check for errors
        if (error == 0) begin
            begin $display("=========== Your Design Passed ==========="); benchmark_done(1); end
        end else begin
            begin $display("Test completed with %d errors.", error); benchmark_done(0); end
        end

        $finish;
    end

endmodule
