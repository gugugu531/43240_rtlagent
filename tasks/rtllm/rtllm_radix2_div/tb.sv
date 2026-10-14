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

    reg clk;
    reg rst;
    reg [7:0] dividend, divisor;
    reg sign;
    reg opn_valid;
    reg res_ready;
    wire res_valid;
    wire [15:0] result;

    // Instantiate the radix2_div module
    TopModule uut (
        .clk(clk),
        .rst(rst),
        .dividend(dividend),
        .divisor(divisor),
        .sign(sign),
        .opn_valid(opn_valid),
        .res_valid(res_valid),
        .res_ready(res_ready),
        .result(result)
    );

    integer i;
    integer error = 0;
    reg [7:0] a_test [0:7];
    reg [7:0] b_test [0:7];
    reg [15:0] expected_result [0:7];
    reg sign_test [0:7];

    initial begin
        // Initialize test vectors
        a_test[0] = 8'd100; b_test[0] = 8'd10; sign_test[0] = 0; expected_result[0] = {8'd0, 8'd10}; 
        a_test[1] = -8'd100; b_test[1] = 8'd10; sign_test[1] = 1; expected_result[1] = {8'd0, -8'd10};
        a_test[2] = 8'd100; b_test[2] = -8'd10; sign_test[2] = 1; expected_result[2] = {8'd0, -8'd10};
        a_test[3] = -8'd100; b_test[3] = -8'd10; sign_test[3] = 1; expected_result[3] = {8'd0, 8'd10};
        a_test[4] = 8'd123; b_test[4] = 8'd123; sign_test[4] = 0; expected_result[4] = {8'd0, 8'd1};
        a_test[5] = 8'd0; b_test[5] = 8'd123; sign_test[5] = 0; expected_result[5] = {8'd0, 8'd0};
        a_test[6] = 8'd123; b_test[6] = 8'd251; sign_test[6] = 0; expected_result[6] = {8'd123, 8'd0};
        a_test[7] = 8'd255; b_test[7] = 8'd7; sign_test[7] = 0; expected_result[7] = {8'd3, 8'd36};

        // Generate clock signal
        clk = 0;
        forever #5 clk = ~clk;
    end

    initial begin
        // Initialize
        rst = 1;
        opn_valid = 0;
        res_ready = 1;
        #20;
        rst = 0;

        for (i = 0; i < 8; i = i + 1) begin
            // Apply test vectors
            dividend = a_test[i];
            divisor = b_test[i];
            sign = sign_test[i];
            opn_valid = 1;
            #10;
            opn_valid = 0;

            // Wait for result
            wait(res_valid);
            #10;

            // Check result
            if (result !== expected_result[i]) begin
                error = error + 1;
                begin tb.benchmark_error = 1; $display("Error: dividend=%d, divisor=%d, expected=%h, got=%h", a_test[i], b_test[i], expected_result[i], result); end
            end

            res_ready = 1;
            #10;
        end

        // Display final result
        if (error == 0) begin
            begin $display("===========Your Design Passed==========="); benchmark_done(1); end
        end else begin
            begin $display("=========== Test completed with %0d/8 failures ===========", error); benchmark_done(0); end
        end

        $finish;
    end
endmodule
