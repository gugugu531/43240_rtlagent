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
    reg rst_n;

    wire [15:0] clk_div;
    wire [15:0] error;
    integer fail_count;
    integer j;

    always #5 clk = ~clk;

    genvar i;
    generate
        for (i = 0; i < 16; i = i + 1) begin : div_case
            localparam integer DIV_VALUE = (i + 1) * 2;

            TopModule #(.NUM_DIV(DIV_VALUE)) uut (
                .clk(clk),
                .rst_n(rst_n),
                .clk_div(clk_div[i])
            );

            freq_divbyeven_checker #(.NUM_DIV(DIV_VALUE)) divider_checker_instance (
                .clk(clk),
                .rst_n(rst_n),
                .clk_div(clk_div[i]),
                .error(error[i])
            );
        end
    endgenerate

    initial begin
        clk = 0;
        rst_n = 0;
        #12 rst_n = 1;
        #1200;

        fail_count = 0;
        for (j = 0; j < 16; j = j + 1) begin
            if (error[j]) begin
                fail_count = fail_count + 1;
            end
        end

        if (fail_count == 0) begin
            begin $display("=========== Your Design Passed ==========="); benchmark_done(1); end
        end
        else begin
            begin $display("=========== Test completed with %0d/16 NUM_DIV cases failing ===========", fail_count); benchmark_done(0); end
        end
        $finish;
    end
endmodule

module freq_divbyeven_checker #(
    parameter NUM_DIV = 6
)(
    input clk,
    input rst_n,
    input clk_div,
    output reg error
);
    reg [3:0] cnt;
    reg expected_clk_div;
    integer check_count;

    initial begin
        error = 0;
        check_count = 0;
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt <= 4'd0;
            expected_clk_div <= 1'b0;
        end
        else if (cnt < NUM_DIV / 2 - 1) begin
            cnt <= cnt + 1'b1;
            expected_clk_div <= expected_clk_div;
        end
        else begin
            cnt <= 4'd0;
            expected_clk_div <= ~expected_clk_div;
        end
    end

    always @(negedge clk or negedge rst_n) begin
        if (!rst_n) begin
            error <= 0;
            check_count <= 0;
        end
        else begin
            check_count <= check_count + 1;
            if (clk_div !== expected_clk_div) begin
                error <= 1;
                begin tb.benchmark_error = 1; $display("Failed NUM_DIV=%0d at check %0d: clk_div=%0d (expected %0d)",
                         NUM_DIV, check_count, clk_div, expected_clk_div); end
            end
        end
    end
endmodule
