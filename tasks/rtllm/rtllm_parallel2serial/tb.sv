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

  reg clk;
  reg rst_n;
  reg [3:0] d;
  wire valid_out;
  wire dout;

  // Instantiate the DUT (Design Under Test)
  TopModule dut (
    .clk(clk),
    .rst_n(rst_n),
    .d(d),
    .valid_out(valid_out),
    .dout(dout)
  );

  // Generate clock
  always #5 clk = ~clk;
  integer error = 0;
  integer failcase = 0;
  integer i = 0;
  initial begin
    for (i=0; i<100; i=i+1) begin
        error = 0;
        // Initialize inputs
        clk = 0;
        rst_n = 0;
        d = 4'b0;

        #10;
        rst_n = 1;
        #10;
        d = $random;
        while (valid_out == 0) begin
            @(posedge clk); // Wait for one clock cycle
        end
        // $display("dout = %b, valid_out = %b", dout, valid_out);
        error = (dout == d[3] && valid_out==1) ? error : error+1;
        #10;
        // $display("dout = %b, valid_out = %b", dout, valid_out);
        error = (dout == d[2] && valid_out==0) ? error : error+1;
        #10;
        // $display("dout = %b, valid_out = %b", dout, valid_out);
        error = (dout == d[1] && valid_out==0) ? error : error+1;
        #10;
        // $display("dout = %b, valid_out = %b", dout, valid_out);
        error = (dout == d[0] && valid_out==0) ? error : error+1;
        #10;
        // $display("dout = %b, valid_out = %b", dout, valid_out);
        error = (valid_out==1) ? error : error+1;
        #10;
        failcase = (error==0)? failcase :failcase+1;

    end
    if(failcase==0) begin
      begin $display("===========Your Design Passed==========="); benchmark_done(1); end
    end
    else begin
      begin $display("===========Test completed with %d /100 failures===========", failcase); benchmark_done(0); end
    end
    $finish; 
  end

endmodule
