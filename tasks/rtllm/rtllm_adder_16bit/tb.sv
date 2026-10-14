`timescale 1ns/1ps

module tb();
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


    reg [15:0] a;
    reg [15:0] b;
    reg Cin;

    wire [15:0] y;
    wire Co;

    wire [16:0] tb_sum;
    wire tb_co;

    assign tb_sum = a + b;
    assign tb_co = tb_sum[16];

    integer i;
    integer error = 0;

    initial begin
        for (i = 0; i < 100; i = i + 1) begin
            a = {$random};
            b = {$random};
            Cin = 0;

            #10;
            error = (y !== tb_sum[15:0] || Co !== tb_co) ? error + 1 : error;
        end

        if (error == 0) begin
            begin $display("===========Your Design Passed==========="); benchmark_done(1); end
        end
        else begin
            begin $display("===========Test completed with %d / 100 failures===========", error); benchmark_done(0); end
        end
    end

    TopModule uut (
        .a(a),
        .b(b),
        .Cin(Cin),

        .y(y),
        .Co(Co)
    );

endmodule
