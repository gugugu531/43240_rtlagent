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
    reg up_down;
    wire [15:0] count;

    // Instantiate the up_down_counter module
    TopModule uut (
        .clk(clk),
        .reset(reset),
        .up_down(up_down),
        .count(count)
    );

    integer error = 0;
    always begin
        #5 clk <= ~clk;
    end

    // Initial 
    initial begin
        clk = 0;
        reset = 1;
        up_down = 1; 
        #10 reset = 0;
    end

    // Monitor for displaying count
    // always @(posedge clk) begin
    //     $display("Count = %d", count);
    // end

    // Test counting up
    initial begin
        #20 up_down = 1;
        #100 up_down = 0; // Switch to counting down
        // $display("Count = %d", count);
        error = (count==11)?error : error+1;
        #200 up_down = 1; // Switch back to counting up
        // $display("Count = %d", count);
        error = (count==65527)?error : error+1;
        #300 ;
        // $display("Count = %d", count);
        error = (count==21)?error : error+1;
        if (error == 0) begin
        begin $display("=========== Your Design Passed ==========="); benchmark_done(1); end
        end
        else begin
        begin $display("=========== Test completed with %d failures ===========", error); benchmark_done(0); end
        end

        $finish;
    end

endmodule
