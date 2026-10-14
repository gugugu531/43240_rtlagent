`timescale 1ns/1ps

module tb;

  parameter N = 16;
  parameter M = 8;
  parameter ITER_MAX = 10;
  localparam TIMEOUT_CYCLES = ITER_MAX + 20;

  reg clk;
  reg rst;
  reg start;
  reg [N-1:0] X;
  wire [N-1:0] sqrt_result;
  wire ready;

  TopModule #(.N(N), .M(M), .ITER_MAX(ITER_MAX)) uut (
    .clk(clk),
    .rst(rst),
    .start(start),
    .X(X),
    .sqrt_result(sqrt_result),
    .ready(ready)
  );

  initial begin clk = 0; forever #5 clk = ~clk; end

  initial begin
    
    
  end

  integer i;
  integer timeout_count;
  integer pass_count;
  integer fail_count;
  reg [N-1:0] test_inputs [0:49];

  real real_input;
  real expected;
  real computed;
  real error;
  real epsilon = 0.01;

  initial begin
    test_inputs[0] = 0;            
    test_inputs[1] = 1;           
    test_inputs[2] = 16;           
    test_inputs[3] = 64;          
    test_inputs[4] = 100;          
    test_inputs[5] = 256;          
    test_inputs[6] = 300;         
    test_inputs[7] = 1024;         
    test_inputs[8] = 4095;  
    for(i = 9; i < 50; i = i + 1) begin
      test_inputs[i] = (i * 123) % 65536;
    end
    test_inputs[10] = 2;      
    test_inputs[11] = 16'hFFFF;
  end

  initial begin
    clk = 0;
    rst = 1;
    start = 0;
    X = 0;
    pass_count = 0;
    fail_count = 0;

    repeat(2) @(posedge clk);
    @(negedge clk);
    rst = 0;
    @(posedge clk);

    for (i = 0; i < 50; i = i + 1) begin
      X = test_inputs[i];

      @(negedge clk);
      start = 1;
      @(posedge clk);
      @(negedge clk);
      start = 0;

      timeout_count = 0;
      while (!ready && timeout_count < TIMEOUT_CYCLES) begin
        @(posedge clk);
        timeout_count = timeout_count + 1;
      end

      if (timeout_count >= TIMEOUT_CYCLES) begin
        $display("Test %0d: TIMEOUT. ready never asserted after %0d cycles (X=%0d)", i, TIMEOUT_CYCLES, X);
        fail_count = fail_count + 1;
      end else if ((sqrt_result == sqrt_result) !== 1'b1) begin
        $display("Test %0d: FAIL. sqrt_result contains unknown bits (%b) for X=%0d -- likely a missing X=0 guard or other uninitialized/corrupted path", i, sqrt_result, X);
        fail_count = fail_count + 1;
      end else begin
        real_input = X / (1.0 * (1 << M));
        computed = sqrt_result / (1.0 * (1 << M));
        expected = $sqrt(real_input);
        error = (computed > expected) ? (computed - expected) : (expected - computed);

        if (error <= epsilon) begin
          $display("Test %0d: PASS. Input=%0d (%.4f), Expected sqrt=%.4f, Computed sqrt=%.4f, Error=%.4f",
                    i, X, real_input, expected, computed, error);
          pass_count = pass_count + 1;
        end else begin
          $display("Test %0d: FAIL. Input=%0d (%.4f), Expected sqrt=%.4f, Computed sqrt=%.4f, Error=%.4f",
                    i, X, real_input, expected, computed, error);
          fail_count = fail_count + 1;
        end
      end

      @(negedge clk);
      rst = 1;
      @(posedge clk);
      @(negedge clk);
      rst = 0;
      @(posedge clk);
    end

    $display("\n=== Testbench Summary ===");
    $display("Mismatches: %0d in %0d samples", fail_count, pass_count+fail_count);
    $display("{\"module\": \"sqrt_newton_raphson_fixedpoint\", \"passed\": %0d, \"failed\": %0d}", pass_count, fail_count);
    if (fail_count > 0) $finish(1);
    $finish;
  end

endmodule
