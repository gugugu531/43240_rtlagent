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


  reg wclk, rclk, wrstn, rrstn, winc, rinc;
  reg [7:0] wdata;
  wire wfull, rempty;
  wire [7:0] rdata;
  
  TopModule #(.WIDTH(8), .DEPTH(16)) dut (
    .wclk(wclk),
    .rclk(rclk),
    .wrstn(wrstn),
    .rrstn(rrstn),
    .winc(winc),
    .rinc(rinc),
    .wdata(wdata),
    .wfull(wfull),
    .rempty(rempty),
    .rdata(rdata)
  );
  
  always #5 wclk = ~wclk;
  always #10 rclk = ~rclk;
  
  initial begin
    wclk = 0;
    rclk = 0;
    wrstn = 0;
    rrstn = 0;
    winc = 0;
    rinc = 0;
    wdata = 0;
  end

  // Apply reset and initialize FIFO
  initial begin
    wrstn = 0;
    rrstn = 0;
    #20;
    wrstn = 1;
    rrstn = 1;
    #10;
    winc = 1; // Enable write
    wdata = 8'hAA; // Write data
    #10;
    winc = 0; // Disable write
    #500;
    rinc = 1;
    #500;
    #10;
    $finish;
  end
  integer outfile1;
  integer outfile2;
  integer outfile3;
  reg[31:0]data1[0:50];
  reg[31:0]data2[0:50];
  reg[31:0]data3[0:50];
  integer i = 0;
  integer error =0;

  initial begin
    #550;
    data1[0] = 'h1;
data1[1] = 'h1;
data1[2] = 'h1;
data1[3] = 'h0;
data1[4] = 'h0;
data1[5] = 'h0;
data1[6] = 'h0;
data1[7] = 'h0;
data1[8] = 'h0;
data1[9] = 'h0;
data1[10] = 'h0;
data1[11] = 'h0;
data1[12] = 'h0;
data1[13] = 'h0;
data1[14] = 'h0;
data1[15] = 'h0;
data1[16] = 'h0;
data1[17] = 'h0;
data1[18] = 'h0;
data1[19] = 'h0;
data1[20] = 'h0;
data1[21] = 'h0;
data1[22] = 'h0;
data1[23] = 'h0;
data1[24] = 'h0;
data1[25] = 'h0;
data1[26] = 'h0;
data1[27] = 'h0;
data1[28] = 'h0;
data1[29] = 'h0;
data1[30] = 'h0;
data1[31] = 'h0;
data1[32] = 'h0;
data1[33] = 'h0;
data1[34] = 'h0;
data1[35] = 'h0;
data1[36] = 'h0;
data1[37] = 'h0;
data1[38] = 'h0;
data1[39] = 'h0;
data1[40] = 'h0;
data1[41] = 'h0;
data1[42] = 'h0;
data1[43] = 'h0;
data1[44] = 'h0;
data1[45] = 'h0;
data1[46] = 'h0;
data1[47] = 'h0;
    data2[0] = 'h0;
data2[1] = 'h0;
data2[2] = 'h0;
data2[3] = 'h0;
data2[4] = 'h0;
data2[5] = 'h0;
data2[6] = 'h0;
data2[7] = 'h0;
data2[8] = 'h0;
data2[9] = 'h0;
data2[10] = 'h0;
data2[11] = 'h0;
data2[12] = 'h0;
data2[13] = 'h0;
data2[14] = 'h0;
data2[15] = 'h0;
data2[16] = 'h0;
data2[17] = 'h0;
data2[18] = 'h0;
data2[19] = 'h0;
data2[20] = 'h0;
data2[21] = 'h0;
data2[22] = 'h0;
data2[23] = 'h0;
data2[24] = 'h0;
data2[25] = 'h0;
data2[26] = 'h0;
data2[27] = 'h0;
data2[28] = 'h0;
data2[29] = 'h0;
data2[30] = 'h0;
data2[31] = 'h0;
data2[32] = 'h1;
data2[33] = 'h1;
data2[34] = 'h0;
data2[35] = 'h0;
data2[36] = 'h0;
data2[37] = 'h0;
data2[38] = 'h0;
data2[39] = 'h0;
data2[40] = 'h0;
data2[41] = 'h0;
data2[42] = 'h0;
data2[43] = 'h0;
data2[44] = 'h0;
data2[45] = 'h0;
data2[46] = 'h0;
data2[47] = 'h0;
    data3[0] = 'h01;
data3[1] = 'h01;
data3[2] = 'hab;
data3[3] = 'hab;
data3[4] = 'hac;
data3[5] = 'hac;
data3[6] = 'had;
data3[7] = 'had;
data3[8] = 'hae;
data3[9] = 'hae;
data3[10] = 'haf;
data3[11] = 'haf;
data3[12] = 'hb0;
data3[13] = 'hb0;
data3[14] = 'hb1;
data3[15] = 'hb1;
data3[16] = 'hb2;
data3[17] = 'hb2;
data3[18] = 'hb3;
data3[19] = 'hb3;
data3[20] = 'hb4;
data3[21] = 'hb4;
data3[22] = 'hb5;
data3[23] = 'hb5;
data3[24] = 'hb6;
data3[25] = 'hb6;
data3[26] = 'hb7;
data3[27] = 'hb7;
data3[28] = 'hb8;
data3[29] = 'hb8;
data3[30] = 'hb9;
data3[31] = 'hb9;
data3[32] = 'h01;
data3[33] = 'h01;
data3[34] = 'h01;
data3[35] = 'h01;
data3[36] = 'hab;
data3[37] = 'hab;
data3[38] = 'hac;
data3[39] = 'hac;
data3[40] = 'had;
data3[41] = 'had;
data3[42] = 'hae;
data3[43] = 'hae;
data3[44] = 'haf;
data3[45] = 'haf;
data3[46] = 'hb0;
data3[47] = 'hb0;
    // outfile1 = $fopen("wfull.txt", "w");
    // outfile2 = $fopen("rempty.txt", "w");
    // outfile3 = $fopen("tdata.txt", "w");
    repeat(48) begin
      #10;
      // $fwrite(outfile1, "%h\n", wfull);
      // $fwrite(outfile2, "%h\n", rempty);
      // $fwrite(outfile3, "%h\n", rdata);
      error = (wfull==data1[i] && rempty == data2[i] && rdata ==data3[i]) ? error:error+1;
      i = i + 1;
    end
    if(error==0)
      begin
        begin $display("===========Your Design Passed==========="); benchmark_done(1); end
            end
      else
      begin
        begin $display("===========Error==========="); benchmark_done(0); end
      end

    // $fclose(outfile1);
    // $fclose(outfile2);
    // $fclose(outfile3);
  end
  // Display FIFO status
  // always @(posedge wclk) begin
  //   $display("wfull=%d, rempty=%d, rdata=%h", wfull, rempty, rdata);
  // end

  initial begin
  repeat (17) begin
    #20;
    if (wfull) begin
      // $display("FIFO is full (wfull=1) at depth %d", $time);
      break;
    end
    winc = 1; // Enable write
    wdata = wdata + 1; // Write data
    #10;
    winc = 0; // Disable write
  end
  end
  
endmodule
