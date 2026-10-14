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
  reg data_in;
  wire data_out;

  // Instantiate the DUT (Design Under Test)
  TopModule dut (
    .clk(clk),
    .rst_n(rst_n),
    .data_in(data_in),
    .data_out(data_out)
  );

  // Generate clock
  initial begin
	clk=0;
	forever #5 clk=~clk;
  end

  integer error = 0;
  initial begin
      // Initialize inputs
      #10;
      rst_n = 0;
      data_in = 0;
      #28;
      rst_n = 1;
      #10      data_in = 0;
      #10      data_in = 0;  
      #10      data_in = 0;
      #10      data_in = 1;
      #10      data_in = 0;
      #10      data_in = 1;
      #10      data_in = 0;
      #10      data_in = 1;
      #10      data_in = 1;
      #10      data_in = 0;
      #10;
      // Finish simulation
      $finish;
  end

  initial begin
    #5;
    #10;
    error = (data_out == 0) ? error : error+1;
    #10;
    error = (data_out == 0) ? error : error+1;
    #10;
    error = (data_out == 0) ? error : error+1;
    #10;
    error = (data_out == 0) ? error : error+1;
    #10;
    error = (data_out == 0) ? error : error+1;
    #10;
    error = (data_out == 0) ? error : error+1;
    #10;
    error = (data_out == 0) ? error : error+1;
    #10;
    error = (data_out == 0) ? error : error+1;
    #10;
    error = (data_out == 1) ? error : error+1;
    // $display("%b,%b,%b", data_in, data_out, dut.pulse_level1);//1
    #20;
    error = (data_out == 1) ? error : error+1;
    #10;
    if (error == 0) begin
        begin $display("===========Your Design Passed==========="); benchmark_done(1); end
    end
    else begin
    begin $display("===========Error==========="); benchmark_done(0); end
    end
  end
endmodule
