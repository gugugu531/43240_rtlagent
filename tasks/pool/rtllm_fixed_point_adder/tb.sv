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

    // Parameters
    parameter Q = 15;
    parameter N = 32;

    // Inputs
    reg [N-1:0] a;
    reg [N-1:0] b;

    // Output
    wire [N-1:0] c;
    reg [N-1:0] expected_result;
    integer error = 0;

    TopModule #(.Q(Q), .N(N)) fp_adder (
        .a(a),
        .b(b),
        .c(c)
    );

    initial begin    
        for (integer i = 0; i < 100; i = i + 1) begin
            a = $random % (1 << N);
            b = $random % (1 << N);

            #10;

            if ((a[N-1] == b[N-1]) || (a[N-1] == 0 && b[N-1] == 1 && a[N-2:0] >= b[N-2:0]) || (a[N-1] == 1 && b[N-1] == 0 && a[N-2:0] < b[N-2:0])) begin
                expected_result = a + b;
            end
            else if (a[N-1] == 0 && b[N-1] == 1 && a[N-2:0] < b[N-2:0]) begin
                expected_result = b - a;
            end
            else begin
                expected_result = a - b;
            end

            if (c !== expected_result) begin
                error = error + 1;
                begin tb.benchmark_error = 1; $display("Test failed: a = %b, b = %b, c = %b, expected_result = %b", a, b, c, expected_result); end
            end
        end

        // Final test result summary
        if (error == 0) begin
            begin $display("=========== Your Design Passed ==========="); benchmark_done(1); end
        end
        else begin
            begin $display("=========== Test completed with %d /100 failures ===========", error); benchmark_done(0); end
        end

        // End simulation
        $finish;
    end

endmodule
