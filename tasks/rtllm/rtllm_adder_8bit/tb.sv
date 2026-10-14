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

  
  reg [7:0] a;
  reg [7:0] b;
  reg cin;
  wire [7:0] sum;
  wire cout;
  
  integer i; // Declare the loop variable here
  integer fail_count;
  integer error = 0;
  
  // Instantiate the module
  TopModule uut (
    .a(a), 
    .b(b), 
    .cin(cin), 
    .sum(sum), 
    .cout(cout)
  );
  
  // Randomize inputs and check output
  initial begin
    for (i = 0; i < 100; i = i + 1) begin
        a = $random & 8'hff;
        b = $random & 8'hff;
        cin = $random & 1'b1;
        #10;
        error = (sum !== a + b + cin) ? error+1 : error; 
    end
    if (error == 0) begin
      begin $display("===========Your Design Passed==========="); benchmark_done(1); end
    end
    else begin
      begin $display("===========Test completed with %d /100 failures===========", error); benchmark_done(0); end
    end

  end

endmodule
