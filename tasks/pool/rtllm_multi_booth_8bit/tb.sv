`timescale 1ns/1ns
`define width 8
`define TESTFILE "test_data.dat"

module tb () ;
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

    reg signed [`width-1:0] a, b;
    reg             clk, reset;

    wire signed [2*`width-1:0] p;
    wire           rdy;

    integer total, err;
    integer i, s, fp, numtests;

    wire signed [2*`width-1:0] ans = a*b;

    TopModule dut( .clk(clk),
        .reset(reset),
        .a(a),
        .b(b),
        .p(p),
        .rdy(rdy));

    // Set up 10ns clock
    always #5 clk = ~clk;

    task apply_and_check;
        input [`width-1:0] ain;
        input [`width-1:0] bin;
        begin
            // Set the inputs
            a = ain;
            b = bin;
            // Reset the DUT for one clock cycle
            reset = 1;
            @(posedge clk);
            // Remove reset 
            #1 reset = 0;

            while (rdy == 0) begin
                @(posedge clk); // Wait for one clock cycle
            end
            if (p == ans) begin
                // $display($time, " Passed %d * %d = %d", a, b, p);
            end else begin
                // $display($time, " Fail %d * %d: %d instead of %d", a, b, p, ans);
                err = err + 1;
            end
            total = total + 1;
        end
    endtask // apply_and_check

    initial begin
        clk = 1;
        total = 0;
        err = 0;

        // Get all inputs from file: 1st line has number of inputs
        apply_and_check(5, 5);
        apply_and_check(2, 3);
        apply_and_check(10, 1);
        apply_and_check(10, 2);
        apply_and_check(20, 20);
        apply_and_check(-128, 2);
        apply_and_check(10, -128);
        apply_and_check(-1, -1);
        apply_and_check(10, 0);
        apply_and_check(0, 2);
        if (err > 0) begin
            begin $display("=========== Failed ==========="); benchmark_done(0); end
        end else begin
            begin $display("===========Your Design Passed==========="); benchmark_done(1); end
        end
        $finish;
    end

endmodule
