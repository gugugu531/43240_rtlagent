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
    reg reset;
    wire [7:0] out;

    TopModule ring_counter_inst (
        .clk(clk),
        .reset(reset),
        .out(out)
    );

    always begin
        #5 clk <= ~clk;
    end

    

    reg [3:0] i;
    reg [7:0] data [0:9] = {8'b00000001, 8'b00000001, 8'b00000010, 8'b00000100, 8'b00001000,8'b00010000, 8'b00100000, 8'b01000000, 8'b10000000, 8'b00000001};

    initial begin
        clk = 0;
        reset = 1;
        i=0;
        #10 reset = 0;
    end
    // Monitor for displaying output
    always @(posedge clk) begin
        
        if (out !== data[i]) begin
            begin tb.benchmark_error = 1; $display("Failed at i=%d, out=%b, expected=%b", i, out, data[i]); end
            // $finish;
        end
        i = i + 1;
    end

    // Stop simulation after checking all values
    always @(posedge clk) begin
        if (i == 9) begin
            begin $display("=========== Your Design Passed ==========="); benchmark_done(1); end
            $finish;
        end
    end
    // Stop simulation after 100 clock cycles
    initial begin
        #100 $finish;
    end

endmodule
